# 개인정보 유출 사고 기술 대응

유출이 의심될 때 BE 대응 담당(1차, 2차, 3차 순서)이 서버에서 하는 일을 순서대로 적는다. 담당자 연락처, 이용자 통지와 기관 신고는 Notion의 개인정보 유출 대응 매뉴얼을 따른다. 운영 기준은 Docs 저장소 `design/operations-privacy.md`의 "유출 사고 때 바로 할 수 있는 차단 조치"다.

> 이 절차의 비밀값 교체 단계는 아직 실제로 시험하지 않았다. 운영에 적용하기 전에 개발 서버에서 먼저 돌려 본다.

## 1. 증거부터 남긴다

차단하면서 로그와 백업이 지워지지 않게, 가장 먼저 사본을 만든다.

| 대상 | 보관 기간 | 남기는 방법 |
| --- | --- | --- |
| 앱·Nginx 로그 (Loki) | 7일 | Grafana Explore에서 의심 기간을 조회해 결과를 내려받는다. 7일이 지나면 자동 삭제된다. |
| 로그인 기록 `login_history` | 3개월 | 아래 SQL로 의심 계정과 IP를 뽑아 파일로 저장한다. |
| 운영 DB 백업 (`ject-db-backups` 버킷) | 7일 | OCI 콘솔에서 사고 직전 날짜의 백업 객체를 내려받아 따로 보관한다. |
| 배포 기록 | 계속 | 운영 앱 VM `/srv/ject/app/deploy-history.jsonl`, `sudo ject-deploy status prod` |

```sql
-- 특정 IP로 로그인하거나 토큰을 갱신한 회원
SELECT member_id, login_type, occurred_at
FROM login_history
WHERE ip_address = '<의심 IP>' AND occurred_at >= '<시작 시각>'
ORDER BY occurred_at;

-- 특정 회원의 접속 IP 이력
SELECT ip_address, login_type, occurred_at
FROM login_history
WHERE member_id = <회원 ID>
ORDER BY occurred_at DESC;
```

## 2. 접근을 막는다

원인이 정해지지 않았으면 위에서부터 차례로 한다.

### 사람의 서버 접근

```sh
for h in ject-dev ject-prod-app ject-prod-data; do ssh <관리자 계정>@$h "sudo ject-user lock <username>"; done
```

Tailscale 관리 콘솔에서 해당 사용자와 기기를 제거한다. GitHub 조직 권한과 Grafana 계정도 회수한다.

### 모든 로그인 세션 종료

운영 DB에서 실행한다. 다음 요청부터 모든 Access Token이 세션 확인에서 401이 되고, 이용자는 다시 로그인한다. 서명 키는 바꾸지 않는다.

```sql
UPDATE auth_session
SET revoked_at = now(), updated_at = now(), version = version + 1
WHERE revoked_at IS NULL;
```

### 토큰 서명 키 교체

세션 종료로 부족하거나 서명 키 유출이 의심될 때만 한다. 이미 발급한 모든 토큰이 무효가 된다.

1. 운영 앱 VM `/srv/ject/secrets/prod-be-auth.env`의 `JWT_SECRET`을 새 값(`openssl rand -base64 64 | tr -d '\n'`)으로 바꾼다.
2. env 파일은 컨테이너를 만들 때 읽으므로 BE 컨테이너를 다시 만든다.
   ```sh
   sudo docker compose -p ject-prod -f /opt/ject/compose/prod-app.yaml --env-file /srv/ject/app/release.env up -d --no-deps --force-recreate --wait be
   ```

`AUTH_TOKEN_ENCRYPTION_KEY`는 바꾸면 저장한 Apple Refresh Token을 읽을 수 없으므로 키 자체가 새어 나갔을 때만 바꾼다.

### DB·Redis 비밀번호 교체

1. 운영 데이터 VM에서 PostgreSQL 관리자 계정으로 `ALTER ROLE ject_app PASSWORD '<새 값>';`을 실행한다.
2. Redis는 `/srv/ject/secrets/redis.conf`의 `requirepass`와 `/srv/ject/secrets/redis_password`(컨테이너 상태 확인이 읽음)를 같은 새 값으로 바꾸고, `docker compose -p ject-prod-data -f /opt/ject/compose/prod-data.yaml --env-file /srv/ject/data.env up -d --force-recreate --wait redis`로 다시 만든다. Redis 관측 전용 계정을 쓰고 있으면 그 비밀번호는 [Redis 지표 수집](observability/redis-README.md)을 따른다.
3. 운영 앱 VM에서 새 값을 앱 env에 반영한다. 표준입력 한 줄로 넘기며 값은 화면에 남기지 않는다.
   ```sh
   printf '%s %s\n' "$NEW_PG" "$NEW_REDIS" | sudo setup-secrets.sh prod-app-env <데이터 VM 사설 IP>
   ```
4. 위 "토큰 서명 키 교체" 2번과 같이 BE 컨테이너를 다시 만든다.

### 외부 연동 키

| 키 | 위치 | 교체 방법 |
| --- | --- | --- |
| Apple 로그인 키 | Apple Developer > Keys | 키를 폐기하고 새로 만든 뒤 `APPLE_KEY_ID`, `APPLE_PRIVATE_KEY_BASE64` 교체 |
| Kakao 앱 키 | Kakao Developers > 앱 키 | 재발급 후 `KAKAO_NATIVE_APP_KEY` 교체(앱도 새 키로 배포 필요) |
| CI 배포 키 | OCI IAM `ject-ci-dev-bot`, `ject-ci-prod-bot` | 해당 API 키 삭제 후 새로 만들어 GitHub Environments 비밀값 교체 |
| 오브젝트 스토리지 키 | OCI IAM 고객 비밀 키 | 삭제 후 새로 만들어 `STORAGE_S3_*` 교체 |

### 문제 있는 배포 되돌리기

```sh
sudo ject-deploy rollback prod be <작업자>
```

## 3. 영향 범위를 센다

회원, 여행과 지출이 한 DB에 있어서 SQL로 바로 셀 수 있다. 신고 기준(1천 명) 판단에 쓴다.

```sql
SELECT count(*) FROM member WHERE status = 'ACTIVE';
SELECT count(DISTINCT member_id) FROM login_history WHERE occurred_at BETWEEN '<시작>' AND '<끝>';
```

## 4. 클라우드 사업자 지원

OCI 콘솔 도움말(?) > Create a Support request에서 Service Request로 접수한다. 지원 요청은 유료 계정만 가능하며 이 계정은 Pay As You Go다. 전화는 오라클 한국 고객지원(+82 1588-8501).

## 5. 마무리

- 막은 접근, 바꾼 키, 지운 세션 수와 시각을 기록한다.
- 원인을 고친 뒤 개발 서버에서 같은 공격 경로가 막혔는지 확인한다.
- 예방 점검은 출시 전 1회, 이후 분기 1회 한다.
