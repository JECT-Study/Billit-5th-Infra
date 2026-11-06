# Redis 관측 — 명시적 선택 설치

2026-11-07. 설치기와 격리 실검증을 준비했다. **실서버 적용·실제 경보 전달·팀 수신 완료를 뜻하지 않는다.** 기본 설치는 계속 비활성이고 `install`·`agent-up`을 명시적으로 실행할 때만 추가한다. 앱/default 계정·비밀번호·축출정책·maxmemory·Redis 프로세스는 변경하지 않는다.

## 현재 설치 기준 — 11/07

`scripts/ject-redis-metrics.py`는 `requirepass`가 설정된 현재 구성에서 관측 전용 `ject_metrics` 사용자를 추가한다. `ACL SETUSER`로 실행 중인 Redis에 적용하고, 기존 `redis.conf` 끝의 관리 구간에 비밀번호 SHA256 해시와 같은 ACL을 기록한다. 파일 inode·소유권·모드를 유지하여 Docker secret의 파일 마운트가 재시작 후에도 같은 설정을 읽도록 한다. `aclfile`/`include` 또는 관리하지 않는 동명 사용자를 발견하면 중단한다. 기존 default 계정은 변경하지 않는다.

현재 권한은 아래와 같다. 키·채널 권한은 없고 `reset` 후 명시한 명령만 허용한다.

```text
reset on -@all +ping +info +slowlog|len +latency|latest +latency|histogram
```

이전 후보의 `CONFIG GET`은 `requirepass` 등 민감 설정을 읽을 수 있어 제거했다. Alloy example의 `config_command="-"`로 해당 수집을 끈다. `SLOWLOG GET`도 제거하며 느린 쿼리 본문을 읽지 않는다. 고정 exporter가 해당 명령을 시도하므로 ACL LOG에는 예상된 SLOWLOG GET 거절이 남을 수 있다. 그 거절을 이유로 권한을 넓히거나 ACL LOG를 지우지 않는다. `SLOWLOG LEN`은 길이만 수집한다. 메모리 사용량과 상한은 INFO 경로에서 계속 수집되는 것을 실검증했다.

공식 근거: [Redis ACL·requirepass·설정 영속화](https://redis.io/docs/latest/operate/oss_and_stack/management/security/acl/), [Alloy1.20 Redis 인자](https://grafana.com/docs/alloy/v1.20/reference/components/prometheus/prometheus.exporter.redis/), [고정 exporter의 CONFIG 비활성화 구현](https://github.com/oliver006/redis_exporter/blob/v1.86.0/exporter/exporter.go), [SLOWLOG 실패 시 선택 지표만 생략하는 구현](https://github.com/oliver006/redis_exporter/blob/v1.86.0/exporter/slowlog.go). Alloy1.20.1 go.mod에서 exporter1.86.0을 확인했다.

### 적용 순서

적용 전 현재 Redis 설정·비밀번호 파일의 권한을 유지한 비공개 백업과 기존 Alloy 구성 사본을 확보한다. 아래 명령은 **대상 서버 root에서** 실행하며, `/tmp/ject-infra`는 검토한 `infra/` 사본이다. 전체 `install-role.sh`는 기존 Alloy 파일을 지우므로 재실행하지 않는다.

```sh
# 개발 VM: 기존 Redis는 127.0.0.1:6379 publish
sudo python3 /tmp/ject-infra/scripts/ject-redis-metrics.py install \
  --role dev --source-dir /tmp/ject-infra --address redis://127.0.0.1:6379
sudo python3 /tmp/ject-infra/scripts/ject-redis-metrics.py verify --role dev
sudo python3 /tmp/ject-infra/scripts/ject-redis-metrics.py agent-up --role dev
```

운영 데이터 VM은 `--role prod-data`와 그 서버의 실제 `DATA_BIND_IP` 주소를 사용한다. 설치기는 고정 컨테이너의 secret 마운트와 published port가 입력 대상과 일치해야 진행한다. 서버 주소·인증값은 이 문서에 저장하지 않는다.

- 관측 비밀번호: `/srv/ject/secrets/redis_metrics_password`, root0400. 신규 생성만 하며 재실행 시 보존한다. 값을 argv/로그/채팅으로 전달하지 않는다.
- 비밀 없는 환경 설정: `/etc/ject/redis-metrics.env`, root0600. Alloy 설정: `/etc/ject/redis-metrics.alloy`. 기본 Alloy 디렉터리 밖에 두어 이중 로딩을 막는다.
- overlay: `/opt/ject/compose/agent-redis.yaml`. `agent-up`은 기존 `obs.env`와 새 env 및 overlay를 함께 사용한다. Compose 구문 및 임시 Alloy validate를 통과한 뒤 **Alloy만** 재생성한다. 짧은 수집 공백은 있을 수 있다.
- 읽기 전용 Alloy 디렉터리 안의 하위 파일 마운트를 위해 `agent-up`은 `/etc/ject/alloy/redis.alloy`를 빈 일반파일로 준비한다. 기존 비어 있지 않은 파일·심볼릭링크는 덮어쓰지 않는다. overlay 제거 뒤 빈 파일은 그대로 두어도 된다. 임시 검증 컨테이너는 시작 실패 때도 정확한 이름으로 정리한다.
- 재부팅 시 Docker의 기존 `unless-stopped` 정책으로 같은 환경·마운트가 유지된다. 이후 수집기 갱신도 이 `agent-up` 명령을 사용한다. overlay 없는 기본 Compose up으로 대체하면 관측 연결이 제거될 수 있다.
- 설치기 파일은 검토 후 `/opt/ject/bin/ject-redis-metrics.py`에0755로 복사할 수 있다. 설치 후 `agent-up`·`verify`·`remove`에는 `--source-dir`가 필요 없다.

### 실제 확인과 되돌리기

`verify` 성공은 ACL 금지명령/필수권한과 파일 영속 설정 일치를 뜻한다. 적용 후 Prometheus의 `redis_up{job="integrations/redis"}`, `redis_memory_used_bytes`, `redis_memory_max_bytes`와 기존 node/app/log 수집을 별도로 확인한다. 실제 host/env 라벨, 누락 경보 및 팀 수신은 이 검사만으로 완료하지 않는다.

되돌릴 때는 **먼저 Alloy를 기존 기본 구성으로 되돌린 다음** 관측 계정을 제거한다.

```sh
sudo docker compose -p ject-agent -f /opt/ject/compose/agent.yaml \
  --env-file /etc/ject/obs.env up -d --no-deps alloy
sudo python3 /opt/ject/bin/ject-redis-metrics.py remove --role dev
```

운영 데이터 VM은 마지막 인자를 `prod-data`로 바꾼다. 제거기는 정확한 관리 구간과 비밀번호 해시를 확인한 뒤 관측 사용자만 삭제하고 해당 구간만 제거한다. 원문에 후속 변경이 있으면 덮어쓰지 않고 중단한다. 재설치/복구를 위해 관측 비밀번호·env·overlay 파일은 보존한다. Redis 재시작·`CONFIG REWRITE`·앱 비밀번호 교체는 수행하지 않는다.

설치 도중 파일 복사/Alloy 검증 등이 실패하면 ACL 준비와 exporter 적용이 분리된 부분 상태일 수 있다. 오류를 성공으로 보지 말고 `verify`와 지표를 확인한다. 같은 비밀번호로 재설치하거나 위 제거 절차를 사용한다. 강제 종료 중의 원자적 다중 파일 변경까지 보장하지 않는다.

### 11/07 검증

- `python3 -B -m unittest discover -s infra/tests -p 'test_redis*.py' -v`:17개 통과. 설정 원문/inode/권한 보존, 재실행, 실패 원복, 사용자 충돌·외부 ACL·후속 수정 거부 포함.
- `python3 -B infra/tests/redis-metrics-install-e2e.py`: 전용 `colima-billit-verify`에서 Redis7.4.11-alpine·Alloy1.20.1로 무재시작 ACL 설치, default와 기존 키 보존, 실제 관측 인증의 CONFIG/SLOWLOG/GET 거절, memory/maxmemory 및 scrape error0 확인. 합성 Redis만 재시작하여 ACL/default 인증/축출정책 영속 확인 후 계정 제거·원문 복구 확인.
- 위 실시험은 설치기의 ACL 함수와 exporter 경로를 검증한다. 실제 서버 mount 검증·전체 CLI/Compose 갱신·호스트 재부팅·원격 쓰기·경보 수신은 운영 적용 단계에서 별도로 확인한다.

## 이전 검증 이력 — 11/06

아래는 이전 후보와 그 당시 결과다. 운영 ACL/설치 명령에는 위 **11/07 현재 기준**을 사용한다. 아래의 CONFIG GET·SLOWLOG GET 권한 후보는 폐기했다.

## 경계와 적용 전 조건

- 기존 `agent.yaml`의 Alloy 1.20.1과 host network를 재사용한다. 별도 exporter 포트를 공개하지 않는다.
- `alloy/redis.alloy.example`은 기본 `install-role.sh` 설치 대상이 아니다. 기본 설정만으로 활성화되지 않는다.
- 아래 제한 ACL 후보로 격리 수집 성공을 실증했다. 모든 권한의 필수성을 하나씩 제거해 증명한 절대 최소 집합은 아니다. 기존 앱/관리자 비밀번호를 임의 재사용하거나 ACL을 자동 확장하지 않는다.
- `JECT_REDIS_METRICS_ADDR`와 `JECT_REDIS_METRICS_USER`는 명시 필수다. 주소는 승인된 대상만, 인증정보 없는 URI/주소로 준다. 기본 사용자·포트·대상을 추정하지 않는다.
- 비밀번호는 별도 opt-in `JECT_REDIS_METRICS_PASSWORD_FILE` 절대경로의 보호된 파일에서 `/run/secrets/redis_metrics_password`로 전달한다. 값은 명령행·환경변수·문서·로그에 넣지 않는다.
- 검토한 설정 파일 절대경로를 `JECT_REDIS_METRICS_CONFIG_FILE`로 지정한다. overlay는 이를 읽기 전용 `/etc/alloy/redis.alloy`에 마운트하며 누락된 호스트 파일을 디렉터리로 만들지 않는다.
- 키값·클라이언트 목록 수집과 클라이언트 이름 설정을 끈다. 키 탐색·개수·스트림·사용자 Lua 스크립트 설정은 넣지 않는다. 로그 수준을 debug로 바꾸거나 키 내용을 출력하지 않는다.

구성만 확인하는 명령(실서버 적용 명령 아님):

```sh
docker compose -f infra/compose/agent.yaml -f infra/compose/agent-redis.yaml config --quiet
```

기존 agent 필수 환경변수와 위 네 변수 모두 필요하다. 이 검사 통과는 ACL/네트워크/Alloy 문법·지표 성공을 뜻하지 않는다. 적용은 대상·ACL·파일 권한 확인 및 별도 승인 후 수행한다. 복구는 overlay를 제외한 원래 Compose 구성으로 돌아가 선택 마운트를 제거하는 방식이며, 실행 전 기존 수집 연속성과 설정 사본을 확인한다. 자동 설치 스크립트를 실행해 복구하지 않는다.

## 검증할 항목과 경보 후보

- 격리 시험에서 인증 실패·정상 연결과 메모리/상한 지표는 확인했다. 실제 host/env 라벨·30초 수집·remote write 경로는 배포 전 별도 대조한다.
- 수집기/Redis 연결 실패와 미수집을 0 사용량으로 해석하지 않는다. 키/사용자 자료가 지표·로그에 담기지 않는지 확인한다.
- 메모리 80% 후보 식(아직 Grafana 규칙에 반영하지 않음):

```promql
(redis_memory_used_bytes / redis_memory_max_bytes > 0.8) and (redis_memory_max_bytes > 0)
```

- `maxmemory=0`, `redis_up=0`, `up=0`, 시계열 부재는 별도 경보/상태 판정이 필요하다. 위 식 하나로 정상/장애를 모두 판단하지 않는다. 유지시간·평가주기·수신처·장애/회복 알림은 별도 합의·실증한다.
- 재배포·복구 후 기존 node/app 지표와 로그 수집이 유지되는지도 확인한다.

## 근거와 검증 범위

[Alloy v1.20 Redis exporter 공식 문서](https://grafana.com/docs/alloy/v1.20/reference/components/prometheus/prometheus.exporter.redis/)의 인자와 targets 연결을 확인했다. 전달받은 1.20.1 소스 기준 SHA는 `95e12cf8961fabc9db6858f7e79bde5c814a07a0`이다. 패키지/이미지 digest를 뜻하지 않는다.

### 2026-11-06 실제 격리 검증

`bash infra/tests/redis-metrics-e2e.sh` 종료 0. Docker context는 `colima-billit-verify`만 사용했고, 홈 마운트·published port·외부 네트워크 없이 합성 데이터로 수행했다. 실서버·운영 Redis 정책은 변경하지 않았다.

- Redis `7.4.11-bookworm`: digest `sha256:44960b3100c48159a66d28c18b0588c193492e25f7551d60e51dd464fc3eca5b`.
- Alloy `v1.20.1`: digest `sha256:2aa2099af76c0098d4af7a4d6e48f86cb66dc1a000222ad927a1c67c6542d13f`.
- 현재 example을 읽은 Alloy validate 성공. `redis_up=1`, scrape error 0, 수집 직후 ACL 거절 0.
- 메모리 약 1.05 MB, 상한 8,388,608 bytes, 축출 계수 0 확인. 합성키 1개를 만든 뒤 격리 상한만 축소하여 축출 계수 1 확인. 지속 부하 시험이 아니다.
- 관측 계정의 GET/SET/EVAL/KEYS/CONFIG SET 거절 확인. 계정 비활성화 시 `redis_up=0`, 복구 시 1. `maxmemory=0` 지표도 확인했다.
- 제한된 합성키/비밀번호 문자열이 최종 지표에 없는지 검사했다. 모든 개인정보 패턴의 비노출 보장은 아니다.
- `bash -n`·ShellCheck 통과. 기존 구조 테스트 3개 통과.

격리에서 통과한 **ACL 명령 허용 후보**(키 패턴 권한 없음):

```text
-@all +ping +info +config|get +slowlog|get +slowlog|len +latency|latest +latency|histogram
```

이 문자열은 계정 생성/배포 명령이 아니다. 기존 앱 사용자에 덧붙이지 않는다. 새 전용 계정은 대상 Redis 관리자 승인과 secret 전달 절차가 필요하다. Redis 7.4 미지원 `arcount`, 전체키 접근, EVAL을 추가하지 않는다. 첫 시험에서 `latency|histogram` 거절을 실제 확인하여 읽기권한만 보완했다. SLOWLOG는 앱 인자를 포함할 수 있는 민감한 읽기권한이므로 운영 도입 전 추가 검토한다. 테스트 fixture의 `default on nopass ... +@all`은 네트워크가 차단된 합성 Redis 제어용이며 운영 ACL로 사용하지 않는다.

### 선택 경보 생성기 — 아직 운영 미반영

```sh
python3 infra/observability/grafana/redis-alerts.py --hosts dev prod-data
```

위 host는 사용 예시이며 승인된 실제 `host` 라벨과 일치하는 목록을 명시해야 한다. 입력 누락·중복·비정상 라벨은 실패한다. 생성기는 **stdout으로 provisioning JSON만 출력**하며 파일·기존 기본 규칙·서버를 변경하지 않는다. `generate.py`의 main 가드와 `rule` 함수를 재사용하고 그 파일이나 생성 rules는 수정하지 않았다. JSON을 설치하거나 서버에 복사하는 단계는 별도다.

| 규칙 | 초안 기준 |
| --- | --- |
| 할당 메모리 | 상한 > 0에서 비율 > 80%, 5분 |
| Redis 연결 | `redis_up < 1`, 2분 |
| 수집 실패/누락 | 명시 대상별 `up=1` 및 `redis_up` 존재를 요구. 둘 중 어느 시계열이든 120초 이상 오래되거나 부재하면 감지, 2분 |
| 무제한 상한 | `redis_memory_max_bytes=0`, 5분; 비율 규칙과 분리 |

평가 주기 1분, 데이터소스 오류는 Alerting. 일반 규칙의 빈 결과는 OK이며 예상 대상이 통째로 사라진 경우는 별도 누락 규칙이 담당한다. 이는 원인별 경보 초안이지 합의된 유지시간/수신정책이 아니다. 여러 Redis 인스턴스를 같은 host로 수집하는 구조는 범위 밖이다.

`python3 -B -m unittest discover -s infra/tests -p 'test_redis_alerts.py' -v`: 입력·stdout 전용·기존 파일 불변·일반 실행의 bytecode 미생성·4규칙 분리·상한0 제외·시계열 신선도 검사 **7개 통과**. 문자열/구조 검사이며 실제 PromQL 계산 결과나 Grafana firing/resolved, Discord·메일 수신을 검증한 것은 아니다. [PromQL 함수](https://prometheus.io/docs/prometheus/latest/querying/functions/)·[연산자](https://prometheus.io/docs/prometheus/latest/querying/operators/)를 참조했다.

남은 검증: 실제 Grafana 평가, 운영 host/env 라벨, remote write, 누락/복구 유지시간, 기존 node/app/log 수집 연속성, 장애/회복 알림의 팀 수신. 실서버 적용 전에는 설정 사본과 overlay 제거 복구 절차를 확인한다.

### 후속 읽기 전용 평가(2026-11-06)
기존 개발 VM Prometheus에 생성된4개 식을 `/api/v1/query`로 평가해 모두 `success`를 확인했다. 대상 `dev`, `prod-data`의 지표누락 식은2개 결과, 나머지3개는0개였다. 수집 미연결 상태의 누락 감지와 문법은 확인했지만 정상/압박/인증실패의 전체 평가·Grafana 지속시간·발송/수신은 미검증이다. 서버 규칙은 설치하지 않았다.

### 합성 PromQL 진리표 검증
`infra/tests/redis-alerts-promql-test.json`의11상태×4식=44평가를 기존 Prometheus3.13.4 `promtool test rules /dev/stdin`에 전달해 SUCCESS(exit0)를 확인했다. 정상80%/초과81%, 상한0, 인증실패, up0, 부재 및120초지연, 대상외host를 포함한다. 현재 생성기와 fixture식 일치도 확인했다. 이전 문단의 정상/압박/인증실패 PromQL 미검증은 이 범위에서 해소됐으며 Grafana 유지시간·발송·수신은 여전히 미검증이다. 서버 파일이나 운영 규칙은 변경하지 않았다.


### Redis job 라벨 계약 보정

`job="integrations/redis"`로 example·생성기·합성 fixture·구조 테스트를 통일했다. 기존 `job_name="redis"`만으로 exporter target의 job을 바꿀 수 있다고 본 것은 잘못이었다.

- [Alloy v1.20.1 Redis 등록 소스](https://github.com/grafana/alloy/blob/v1.20.1/internal/component/prometheus/exporter/redis/redis.go#L22)는 exporter 이름을 `redis`로 전달한다.
- [공통 exporter 소스](https://github.com/grafana/alloy/blob/v1.20.1/internal/component/prometheus/exporter/exporter.go#L124-L140)는 target에 `job="integrations/redis"`를 지정한다.
- [v1.20 scrape 인자 문서](https://grafana.com/docs/alloy/v1.20/reference/components/prometheus/prometheus.scrape/#arguments)의 `job_name`은 target에 job이 없을 때만 사용한다. example도 같은 값으로 명시하여 이 계약을 드러낸다. 별도 relabel 계층은 추가하지 않았다.

이는 **고정 버전 공식 구현과 현재 설정에 근거한 라벨 추론**이다. 앞선 격리 시험은 exporter 원시 `/metrics`를 직접 읽었으며 최종 scrape→host/env→remote-write 라벨을 관측한 것이 아니다. 이 전체 경로 실측은 여전히 남아 있다. 합성 PromQL 시험은 수정된 계약의 fixture로 재실행하며 운영 지표 유입을 증명하지 않는다.

보정 후 검증: `python3 -B -m unittest discover -s infra/tests -p 'test_redis*.py' -v` **11개 통과**(리더가 추가한 fixture/생성기 일치 검사 포함). 같은 수정 fixture를 기존 개발 Prometheus 3.13.4의 `promtool test rules /dev/stdin`으로 재평가하여 **44평가 SUCCESS, 종료 0**. 서버 파일·설정·경보·VM 상태는 변경하지 않았다.

### 최종 수집 라벨 경로 실제 검증(10:33)
`infra/tests/redis-remote-write-e2e.py`로 실제 Redis→Alloy scrape→기존 common.alloy host/env/instance relabel→remote_write→격리 Prometheus3.13.4 조회를 확인했다. job=integrations/redis, host=synthetic, env=test, instance=synthetic, redis_up=1, 메모리>0, maxmemory=8388608. 운영과 분리한 내부 Docker네트워크·tmpfs·제한메모리만 사용했고 원본자료/운영비밀/호스트포트/바인드마운트 없음. 실행exit0 뒤 root도 컨테이너0·기본네트워크3·기존볼륨2동일 확인. VM10:33:39중지. 따라서 앞선 '최종 라벨 실측 미검증'은 이 합성 경로 범위에서 해소됐다. 운영라벨·remote write인증·Grafana유지시간·수신은미검증.

후속 코드검토에서 inspect 실패를 부재로 해석하지 않도록 정리검사를 성공한 목록조회+정확이름대조로 보완했고, 조회실패/잔존/정상부재3개회귀통과. 그 정리검사 코드 변경 뒤 전체E2E재실행은 하지 않았다. 실제위시험의 정리결과는 root별도목록조회로확인했다.
