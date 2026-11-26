# 서버 접속

개발팀은 Tailscale과 개인 SSH 키로 서버에 접속한다.

## 접속 방식

- 서버 22번은 인터넷에 안 열려 있다. **Tailscale**로 들어간다.
  - 인프라 담당의 Tailscale 네트워크(tailnet)에 서버 3대가 `tag:ject`로 들어가 있고, 팀원은 초대받은 멤버.
  - 접근 정책(콘솔 Access controls): 팀원은 `tag:ject`의 tcp/22만. 담당자의 다른 기기는 팀원에게 안 보인다.
  - 서버 이름: `ject-prod-app`, `ject-prod-data`, `ject-dev`. MagicDNS라 이름으로 바로 ssh 된다.
- 로그인은 서버에 등록한 **각자 공개키**로. 비밀번호 로그인 없음. 계정은 `ject-admins` 그룹(sudo).
- CI(deploy 계정)는 그대로 OCI Bastion으로 들어온다. 사람은 Bastion을 비상용으로만 쓴다(아래).

호스트 키 지문 (처음 접속할 때 뜨는 값과 같아야 한다)

| 서버 | SHA256 |
| --- | --- |
| ject-prod-app | `R7estBH8fd1sAUsmRy5a0uIbjC1PnHoU86w/y7ILzvY` |
| ject-prod-data | `7w9aJRmiLkJMC8IiS+53aQcdfQlbclycjkzsggpRE7c` |
| ject-dev | `BOaNMvOwxaITg+0tqf7qDhD6IKhf9YdS8d1q2/zbdMg` |

## 처음 접속하는 순서 (팀원)

1. 메일로 온 Tailscale 초대를 수락하고, 인프라 담당이 승인할 때까지 기다린다.
2. Tailscale 앱을 설치해 초대받은 계정으로 로그인한다.
3. **앱의 계정 메뉴에서 초대받은 네트워크로 바꾼다.** 로그인하면 본인 개인 네트워크로 들어가는 경우가 많다. 목록에 없으면 같은 계정으로 다시 로그인해 네트워크를 고른다.
4. 앱의 Devices 탭에 `ject-dev`, `ject-prod-app`, `ject-prod-data`가 보이면 된 것이다.
5. `ssh <아이디>@ject-dev`(나머지 두 대도 같음). 처음 접속 때 나오는 SHA256 값이 위 표와 같은지 본다.

## DB·Redis 접속

서버 계정과 따로다. 개발과 운영은 계정 이름, 비밀번호, 데이터가 모두 다르다.

| 환경 | 서버 | DB 이름 | 앱 계정 | 관리자 계정 |
| --- | --- | --- | --- | --- |
| 개발 | `ject-dev` | `ject_dev` | `ject_dev_app` | `ject_admin` |
| 운영 | `ject-prod-data` | `ject` | `ject_app` | `ject_admin` |

- 앱 계정은 자기 DB의 주인이다. 테이블을 만들고 고칠 수 있고(Flyway 포함), 다른 DB는 못 본다. 관리자 계정은 계정·DB 생성까지 전부 된다.
- 운영 DB에는 사람(BE)마다 읽기 전용 계정이 있다. 아이디는 서버 계정과 같고 비밀번호는 `sudo cat /srv/ject/secrets/pg_person_<아이디>_password`로 본다. 운영 데이터를 볼 때는 이 계정을 쓰고, 쓰기가 필요한 관리 작업만 `ject_admin`으로 한다. 두 계정 모두 실행한 SQL이 기록된다(아래 「접속 기록과 분기 점검」).
- Redis는 계정 없이 비밀번호 하나다.
- 비밀번호는 해당 서버에서 `sudo cat /srv/ject/secrets/<파일>`로 본다. 앱 계정 `pg_app_password`, 관리자 `pg_admin_password`, Redis `redis_password`.
- 배포할 때는 서버가 앱에 접속값을 넣어 준다(`/srv/ject/secrets/dev-be.env`, `prod-be.env`). yml이나 코드에 비밀번호를 적지 않는다.
- 소셜 로그인·JWT 값은 따로 `/srv/ject/secrets/dev-be-auth.env`, `prod-be-auth.env`에 있다(`setup-secrets.sh`가 DB 파일을 다시 만들 때 지워지지 않게 분리). 앱에는 환경 변수로 들어간다.

  | 변수 | 내용 |
  | --- | --- |
  | `JWT_SECRET` | 토큰 서명 키. 개발과 운영이 다르다 |
  | `GOOGLE_CLIENT_ID` | 구글 ID 토큰 `aud` 검증값. 개발은 개발용, 운영은 출시용 웹 클라이언트 ID |
  | `KAKAO_NATIVE_APP_KEY` | 카카오 ID 토큰 `aud` 검증값 |
  | `APPLE_TEAM_ID`, `APPLE_KEY_ID`, `APPLE_CLIENT_ID` | 애플 client secret 생성과 ID 토큰 `aud` 검증값 |
  | `APPLE_PRIVATE_KEY_BASE64` | 애플 .p8 키 파일 내용을 base64로 한 줄로 만든 값 |
  | `AUTH_TOKEN_ENCRYPTION_KEY` | 애플 refresh token을 DB에 암호화해 저장할 때 쓰는 키(base64 32바이트). 바꾸면 저장된 토큰을 못 읽는다 |
  | `POLICY_CONTENT_BASE_URL` | 가입 화면 약관 전문 주소의 앞부분(`{값}/{약관 종류}/{버전}`). 호스트는 서비스 주소를 따르고 `ject-domain switch`가 바꾼다. 약관 페이지는 아직 없다 |
  | `TRIP_INVITATION_BASE_URL` | 초대 링크 주소의 앞부분(`{값}/{초대 코드}`). FE 웹 경로 `/invitations/{초대 코드}`에 맞춘다. 호스트는 `ject-domain switch`가 바꾼다 |
  | `GEMINI_API_KEY` | 영수증 인식에 쓰는 Gemini API 키(유료 등급). 없으면 서버는 뜨고 영수증 인식 API만 503을 준다. 모델은 `GEMINI_MODEL`(기본값은 서버 `docs/operations/configuration.md`)로 바꾸고, 엔진 자체는 `RECEIPT_RECOGNITION_PROVIDER`로 고른다 |

노트북에서 붙기: DB·Redis 포트는 인터넷과 Tailscale 어디에도 안 열려 있어서, SSH로 서버를 거쳐 노트북 포트로 넘긴다. 이 명령을 띄운 터미널을 닫으면 끊긴다.

```sh
# 개발: 노트북 25432 → 개발 DB, 26379 → 개발 Redis
ssh -N -L 25432:127.0.0.1:5432 -L 26379:127.0.0.1:6379 <아이디>@ject-dev

# 운영: 데이터 서버의 사설 IP로 넘긴다
IP=$(ssh <아이디>@ject-prod-data '. /srv/ject/data.env; echo $DATA_BIND_IP')
ssh -N -L 35432:$IP:5432 -L 36379:$IP:6379 <아이디>@ject-prod-data
```

DB 툴(DBeaver, DataGrip 등)에는 호스트 `127.0.0.1`, 포트 `25432`(개발) 또는 `35432`(운영)와 위의 DB 이름·계정·비밀번호를 넣는다. Redis 툴은 `127.0.0.1:26379`(개발) 또는 `36379`(운영)에 비밀번호만 넣는다. 로컬 compose가 15432·16379를 쓰므로 겹치지 않게 골랐다.

## 팀원이 보낼 것

1. SSH 공개키 한 줄 (`~/.ssh/id_ed25519.pub` 내용). 개인키는 절대 안 받는다.
2. Tailscale 초대받을 이메일 (구글, 마이크로소프트, 깃허브, 애플 계정 중 하나).

## 계정 관리

1. 공개키를 `.local/ject-access/<username>.pub`에 저장하고 `team.yaml`의 상태를 고친다(이메일은 파일에 적지 않는다). username은 팀원이 지정한 영문 소문자 아이디를 사용한다.
2. 계정 생성(공개키는 표준입력으로 넘긴다). 운영 서버 2대(`ject-prod-app`·`ject-prod-data`)에는 개인정보 취급자인 BE만 만들고, FE는 `ject-dev`에만 만든다(팀 개인정보 내부 관리계획 3.1 최소 인원).
   ```sh
   for h in ject-dev ject-prod-app ject-prod-data; do
     ssh seongju@$h 'f=$(mktemp); cat > "$f"; sudo ject-user add <username> "$f" "<이름>"; rm -f "$f"' < .local/ject-access/<username>.pub
   done
   ```
3. Tailscale 콘솔 → Users → Invite users → 이메일 입력.
4. 본인이 `ssh <username>@ject-dev` 되는지 확인받기.
5. 이미 계정이 있는 팀원이 기기를 하나 더 쓰면(예: 폰) 그 기기에서 새로 만든 공개키를 받아 `sudo ject-user addkey <username> <파일>`로 덧붙인다. `add`는 키를 한 줄로 바꾸므로 쓰지 않는다. 다른 기기의 개인키를 옮겨 쓰지 않게 안내한다.
6. 운영 서버 계정을 만든 BE는 운영 DB 계정도 만든다: `ssh seongju@ject-prod-data 'sudo ject-db-person add <username>'`.
7. 나갈 때: 7일 안에 계정이 있는 서버마다 `sudo ject-user lock <username>`, Tailscale 콘솔에서 사용자 제거, 운영 DB 계정은 `sudo ject-db-person lock <username>`. 그 사람이 볼 수 있던 DB·Redis 비밀번호와 외부 API 키를 교체하고 `team.yaml`에 회수일을 적는다(팀 개인정보 내부 관리계획 3.1).

## 접속 기록과 분기 점검

팀 「개인정보 내부 관리계획」에 따라 운영 서버 2대의 취급자 접속 기록을 1년 보관한다.

| 기록 | 남기는 곳 | 올리는 것 |
| --- | --- | --- |
| SSH 로그인, sudo 명령 | 서버 journald(`_COMM=sshd`, `SYSLOG_IDENTIFIER=sudo`) | 운영 앱·운영 데이터 |
| 운영 DB 접속·종료, 사람 계정(`ject_admin`, `ject_person` 구성원)이 실행한 SQL | PostgreSQL 로그(`log_connections`, `log_disconnections`, 역할별 `log_statement=all`) | 운영 데이터 |

- `ject-access-log-ship.timer`가 매일 00:30(KST)에 전날치를 `ject-access-logs` 버킷의 `<서버>/<연도>/<날짜>.log.gz`로 올린다. 앱 계정(`ject_app`)의 SQL은 담지 않는다.
- 서버에는 이 버킷의 생성 권한만 있어 지난 파일을 읽거나 지우거나 덮어쓰지 못한다. 365일이 지난 파일은 버킷 수명 주기 규칙이 지운다.
- 하루치를 다시 만들 수는 없으니(덮어쓰기 금지) 실패하면 `sudo journalctl -u ject-access-log-ship`으로 원인을 보고 `sudo ject-access-log-ship <날짜>`로 그날치를 올린다. 서버 journald는 약 5주, PostgreSQL 컨테이너 로그는 30MB까지만 남는다.
- 분기 점검(출시 전 1회, 이후 분기 1회): 관리자 PC에서 그 분기 파일을 받아 새벽 대량 조회, 등록되지 않은 계정·기기의 접속, 운영 DB 내려받기(`COPY`, `pg_dump`)가 있는지 보고 결과를 팀 Notion 점검 기록에 남긴다.

```sh
oci os object list --profile JECT --auth security_token -bn ject-access-logs --prefix ject-prod-data/2026/ --query 'data[].name'
oci os object get --profile JECT --auth security_token -bn ject-access-logs --name ject-prod-data/2026/2026-11-25.log.gz --file - | gzip -dc | less
```

## 비상용: Bastion (Tailscale이 안 될 때)

A1(ARM) + Ubuntu는 Bastion 관리형 SSH가 안 돼서 포트 포워딩 세션만 쓴다. OCI 콘솔 계정과 MFA가 필요하다.

```sh
OCI_PROFILE=JECT infra/access/ject-ssh.sh <username> <prod-app|prod-data|dev>
```

세션은 최대 3시간이며, 동시 세션 한도에 도달하면 기존 세션을 정리한 뒤 다시 연결한다.
팀원 OCI 계정은 지금 안 만든다. 필요해지면 `ject-developers` 그룹에 넣는다.

## 서버에서 지키기

- DB, Redis, nginx는 `docker compose`로 직접 올리고 내리지 않는다. 배포는 CI 또는 `sudo ject-deploy`.
- `/srv/ject/secrets` 안의 값은 본인 DB 툴에 넣을 때만 본다. 채팅, 문서, 커밋에 붙여 넣지 않는다.
- 운영 DB의 데이터는 신중하게 다룬다. 데이터를 고치거나 지우는 쿼리는 먼저 팀에 알린다.
- 운영 데이터 서버에서 뭔가 지우거나 복원하려면 먼저 인프라 담당과 얘기한다.
- 서버 도구: `sudo ject-deploy status prod|dev`(배포 상태), `sudo cat /srv/ject/backup-status/last.json`(마지막 백업), `sudo docker ps`.
