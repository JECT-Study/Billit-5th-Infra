# JECT 인프라 실행 정의

설계 원본은 [`docs/인프라-설계.md`](../docs/인프라-설계.md), 이번 실행 범위는 [`docs/다음세션-인프라-구축.md`](../docs/다음세션-인프라-구축.md).
이 폴더는 실제 구축에 쓰는 코드다. **무엇이 실제로 적용·검증됐는지는 `docs/인프라-설계.md`의 "구축 결과" 절**을 본다.
모니터링·알림(Prometheus·Loki·Grafana·Alloy·Node Exporter·OCI Monitoring 알람·Notifications)은 2026-10-15 밤에 추가했다(아래 「모니터링」).
OCI Health Checks는 무료 한도가 없어 쓰지 않는다(공인 주소 시험으로 대신). OTel·Tempo는 범위 밖이다.

## 구성

| 경로 | 내용 |
| --- | --- |
| `oci/` | OpenTofu: Compartment `JECT`, VCN(10.20.0.0/16)·공개/데이터/개발 서브넷·IGW·NAT·Service GW, 역할별 NSG, Bastion, VM 3대(A1 1 OCPU/6GB/50GB, Ubuntu 24.04 aarch64), 예약 공인 IP, 비공개 버킷 3개, 인스턴스 주체 정책, `ject-developers` 그룹 정책 |
| `cloud-init/` | 관리자 계정만 만드는 최소 부트스트랩 |
| `scripts/bootstrap-host.sh` | Docker Engine·Compose, 로그 순환(10m×3), journald 제한, 무인 보안 업데이트(자동 재부팅 없음), 디렉터리, `deploy` 계정, SSH 비밀번호 금지 |
| `scripts/install-role.sh` | 역할별 스크립트·Compose·systemd 설치 |
| `scripts/setup-secrets.sh` | 서버 안에서 비밀값 생성(출력 안 함, 덮어쓰지 않음) |
| `scripts/ject-deploy` | 앱 배포·롤백·상태: flock 동시 배포 금지, digest 고정, 허용 레지스트리, 디스크 확인, healthcheck+readiness+Nginx 경유 확인, 실패 시 이전 이미지 자동 복구, 이력 기록 |
| `scripts/ject-pg-backup` | 운영 DB 일일 백업(04:00 KST) → `ject-db-backups` 버킷, 체크섬·행 수 MANIFEST, 성공 7개 보존, 실패 시 기존 보존 |
| `scripts/ject-pg-restore-test` | 버킷 백업을 격리 임시 컨테이너(--network none)에 복원해 행 수 비교(매월 1일) |
| `scripts/ject-cert` | Let's Encrypt 발급·갱신(webroot), 갱신 시에만 Nginx 재적용 |
| `scripts/render-nginx.sh` | 인증서 유무에 따라 Nginx 설정 생성. 관리 경로(/actuator 등) 차단, 쿼리 문자열 없는 JSON 접근 로그 |
| `scripts/ject-user` | 개발자 계정 추가·잠금(공개키 검사, 개인키 거부) |
| `scripts/ject-deploy-gate` | `deploy` 계정의 SSH 강제 명령. `ject-deploy deploy|rollback|status <이 VM의 환경> ...`만 검사 후 sudo로 실행(셸·포워딩·주입 불가) |
| `scripts/ject-deploy-key` | 환경별 CI 배포 공개키를 `deploy` 계정에 등록(`from="<Bastion IP>",restrict,command="ject-deploy-gate"`) |
| `compose/` | `prod-edge`(Nginx·Certbot), `prod-app`(앱), `prod-data`(PostgreSQL 17.11·Redis 7.4.11), `dev-*`(개발 앱·DB·게이트웨이) |
| `systemd/` | 백업·복원 시험·인증서 갱신 타이머, 백업 결과 지표(`ject-backup-metrics`), 알림 중계(`ject-alert-relay`) |
| `oci/monitoring.tf` | 알림 주제 `ject-alerts`·이메일 구독, VM 응답 없음(3)·메모리 90% 알람, 개발 VM의 발행 권한 |
| `observability/` | Prometheus·Loki·Alloy(공통·앱·관측) 설정, obs-gateway(쓰기 전용), 알림 중계기, Grafana 프로비저닝(`grafana/generate.py`로 규칙·대시보드 생성) |
| `compose/agent.yaml`, `compose/obs.yaml` | 수집기(3대: Node Exporter·Alloy), 관측 스택(개발 VM: Prometheus·Loki·Grafana·obs-gateway) |
| `smoke-app/` | **실제 JECT 앱이 아님.** 배포 경로 검증용 최소 이미지(/healthz, /readyz=DB·Redis 연결, /version) |
| `github-workflows/` | 앱 저장소의 `.github/workflows/`에 넣을 ARM64 빌드·GHCR·Bastion(포트 포워딩) 배포 워크플로. 옮기는 방법·권한은 `github-workflows/README.md` |
| `access/` | 팀원 계정·접속 방법(Tailscale, 비상용 Bastion 스크립트), 팀원에게 보내는 안내문 |
| `tests/` | 로컬 통합 시험(`local-e2e.sh` 배포·백업, `local-obs-e2e.sh` 모니터링·Swagger·Redis 정책)과 OCI CLI 대역 |

## 서버 배치

| VM | 서브넷 | 실행 | 외부에서 열린 포트 |
| --- | --- | --- | --- |
| `ject-prod-app` | 공개(예약 공인 IP) | `ject-edge`(Nginx·Certbot), `ject-prod`(be, fe) | 80, 443 |
| `ject-prod-data` | 사설 | `ject-prod-data`(PostgreSQL, Redis), 백업 타이머 | 없음. 5432·6379는 운영 앱 NSG에서만 |
| `ject-dev-obs` | 사설 | `ject-dev-gateway`(Nginx :8080), `ject-dev`(be, fe), `ject-dev-data` | 없음. 8080은 운영 앱 NSG에서만 |

SSH 22는 NSG에서 Bastion 엔드포인트 /32만 허용한다(인터넷에 열지 않음). 사설 VM의 아웃바운드는 NAT, Object Storage는 Service Gateway.
사람은 **Tailscale**로 들어간다(2026-10-16부터, `scripts/install-tailscale.sh`, 서버는 `tag:ject`, 팀원은 tcp/22만 — `access/README.md`).
Tailscale은 서버가 바깥으로 연결을 거는 방식이라 NSG에 추가로 열 포트가 없다.
CI는 그대로 Bastion 포트 포워딩 세션(A1+Ubuntu는 관리형 SSH 세션이 안 됨). CI 사용자는 `target.resource.ocid` 조건으로 자기 VM 대상 세션만 만들 수 있고, 세션 조회·VNIC 조회 권한이 따로 필요하다(`oci/storage_iam.tf`).
sshd는 키 로그인만, `AllowGroups ject-admins deploy`, `MaxAuthTries 3`.

## 구축 순서 (요약)

1. `oci/`: `terraform.tfvars`(저장소 제외)에 `tenancy_ocid`, `admin_ssh_public_key` → `tofu plan` → 확인 후 `tofu apply`.
2. 각 VM: `infra/`를 `/tmp/ject-infra`로 복사 → `sudo bash bootstrap-host.sh <role>` → `sudo bash install-role.sh <role>`.
3. 데이터 VM: `setup-secrets.sh prod-data` → `/srv/ject/data.env`에 `DATA_BIND_IP=<사설IP>` → `docker compose -p ject-prod-data -f /opt/ject/compose/prod-data.yaml --env-file /srv/ject/data.env up -d --wait`.
4. 앱 VM: 데이터 VM의 앱 DB·Redis 비밀값을 표준입력으로 `setup-secrets.sh prod-app-env <데이터 사설IP>`에 전달(화면 출력 없음) → `render-nginx.sh edge` → `ject-edge` 기동 → `ject-deploy deploy prod be <image@digest>`.
5. 개발 VM: `setup-secrets.sh dev`, `dev-app-env` → `ject-dev-data`, `ject-dev-gateway` 기동 → `ject-deploy deploy dev be ...`. 운영 Nginx의 `DEV_UPSTREAM=<개발 사설IP>:8080`.
5-1. CI: 환경별 배포 키 공개키를 `ject-deploy-key install <pub> <Bastion 사설 IP>`(운영 앱·개발 VM) → GitHub Environment 비밀값(`github-workflows/README.md`).
6. 도메인이 생기면 `/srv/ject/app/edge.env`에 `PROD_DOMAIN`, `DEV_DOMAIN` → DNS A 레코드 → `ject-cert issue`.
7. 백업: `systemctl start ject-pg-backup` → `ject-pg-restore-test latest` 성공 확인.

## 모니터링

```text
각 VM: Node Exporter(127.0.0.1:9100) ─┐
       앱 관리 포트(127.0.0.1:18081) ──┼─ Alloy(수집·민감정보 가림) ──▶ 개발 VM obs-gateway(사설 IP 9090·3100, 쓰기 경로만, Basic 인증)
       컨테이너 로그·systemd 로그 ─────┘                                     │
개발 VM: Prometheus(14일·8GB) · Loki(7일) ◀─────────────────────────────────┘
         Grafana(127.0.0.1:3000) ── 알림 ──▶ ject-alert-relay(127.0.0.1:9095) ──▶ OCI Notifications ject-alerts ──▶ 이메일
         Alloy blackbox: NAT → 공인 HTTPS /readyz·인증서(1분)       OCI Monitoring 알람(VM 응답 없음·메모리) ──┘
```

- 운영 VM에는 새 인바운드 포트가 없다(밀어 넣기). NSG는 운영 VM → 개발 VM 9090·3100만 추가했다.
- **Grafana 접속(관리자):** `ssh -N -L 3000:127.0.0.1:3000 seongju@ject-dev`(Tailscale) → 브라우저 `http://127.0.0.1:3000`(창을 닫으면 터널 종료).
  Tailscale이 안 될 때만 `JECT_SSH_ARGS="-N -L 3000:127.0.0.1:3000" OCI_PROFILE=JECT bash access/ject-ssh.sh seongju dev`(Bastion).
  관리자 비밀번호: 개발 VM `sudo cat /srv/ject/secrets/grafana_admin_password`(사용자 `admin`). 팀원 계정은 사람마다 따로 만든다.
- 대시보드: 「JECT 개요」(서버·백업·공인 주소·인증서·관측 도구), 「JECT 앱」(HTTP·JVM·Hikari), 「JECT 로그」.
  규칙·대시보드는 `observability/grafana/generate.py`를 고치고 다시 생성한 뒤 `install-role.sh dev`로 반영한다(Grafana 재시작 필요).
- 알림 규칙 15개: 서버 지표 끊김·디스크 80/90%·메모리 15%·CPU 85%, 백업 실패·26시간 성공 없음·복원 시험 실패, 공인 주소 실패·인증서 14일,
  앱 지표 끊김·5xx 5%·p95 1초·DB 커넥션 대기·운영 오류 로그. OCI 알람: VM 응답 없음(5분)·메모리 90%(10분).
- 설치 순서(개발 VM): `setup-secrets.sh obs` → `PROBE_PROD_URL=… PROBE_DEV_URL=… setup-secrets.sh obs-env dev dev <개발 IP>` →
  `/etc/ject/alert-relay.env`에 `ALERT_TOPIC_ID=$(tofu output -raw alert_topic_id)` → `docker compose -p ject-obs -f obs.yaml --env-file /etc/ject/host.env up -d` →
  `systemctl enable --now ject-alert-relay` → `docker compose -p ject-agent -f agent.yaml --env-file /etc/ject/obs.env up -d`.
  운영 VM: 개발 VM의 `obs_push_password`를 표준입력으로 `setup-secrets.sh obs-push` → `obs-env <prod-app|prod-data> prod <개발 IP>` → `ject-agent` 기동.
- 알림 경로 시험: 개발 VM에서 `curl -X POST http://127.0.0.1:9095/test` → 시험 메일 1통.

## 로컬 검증

```sh
colima start --cpu 2 --memory 3
colima ssh -- sudo bash "$PWD/infra/tests/local-e2e.sh"
```
OCI 대신 `tests/fake-oci.py`를 쓰므로, 실제 버킷·인스턴스 주체 권한은 서버에서 따로 검증한다.
모니터링: `colima ssh -- sudo bash "$PWD/infra/tests/local-obs-e2e.sh"`(중계기는 DRY_RUN — 실제 OCI 발행은 서버에서 확인).
