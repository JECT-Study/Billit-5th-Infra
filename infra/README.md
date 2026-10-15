# JECT 인프라 실행 정의

설계 원본은 [`docs/인프라-설계.md`](../docs/인프라-설계.md), 이번 실행 범위는 [`docs/다음세션-인프라-구축.md`](../docs/다음세션-인프라-구축.md).
이 폴더는 실제 구축에 쓰는 코드다. **무엇이 실제로 적용·검증됐는지는 `docs/인프라-설계.md`의 "구축 결과" 절**을 본다.
모니터링·장애 감지(Grafana·Prometheus·Loki·Alloy·Node Exporter·OTel·Tempo·OCI 알람·Health Checks)는 이번 범위가 아니므로 여기 없다.

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
| `systemd/` | 백업·복원 시험·인증서 갱신 타이머 |
| `smoke-app/` | **실제 JECT 앱이 아님.** 배포 경로 검증용 최소 이미지(/healthz, /readyz=DB·Redis 연결, /version) |
| `github-workflows/` | 앱 저장소의 `.github/workflows/`에 넣을 ARM64 빌드·GHCR·Bastion(포트 포워딩) 배포 워크플로. 옮기는 방법·권한은 `github-workflows/README.md` |
| `access/` | 팀원 계정 정책·공개키 제출·macOS/Windows 접속 안내, Bastion 포트 포워딩 접속 스크립트, 팀원 요청 안내문 |
| `tests/` | 로컬 통합 시험(`local-e2e.sh`)과 OCI CLI 대역 |

## 서버 배치

| VM | 서브넷 | 실행 | 외부에서 열린 포트 |
| --- | --- | --- | --- |
| `ject-prod-app` | 공개(예약 공인 IP) | `ject-edge`(Nginx·Certbot), `ject-prod`(be, fe) | 80, 443 |
| `ject-prod-data` | 사설 | `ject-prod-data`(PostgreSQL, Redis), 백업 타이머 | 없음. 5432·6379는 운영 앱 NSG에서만 |
| `ject-dev-obs` | 사설 | `ject-dev-gateway`(Nginx :8080), `ject-dev`(be, fe), `ject-dev-data` | 없음. 8080은 운영 앱 NSG에서만 |

SSH 22는 세 VM 모두 Bastion 엔드포인트 /32에서만 허용한다. 사설 VM의 아웃바운드는 NAT, Object Storage는 Service Gateway.
A1(ARM) + Ubuntu는 Bastion **관리형 SSH 세션을 지원하지 않으므로**(OCI 알려진 문제) 사람·CI 모두 **포트 포워딩 세션**으로 22번에 터널을 연 뒤
VM에 등록된 키로 로그인한다. CI 사용자는 `target.resource.ocid` 조건으로 자기 VM 대상 세션만 만들 수 있고, 세션 조회·VNIC 조회 권한이 따로 필요하다(`oci/storage_iam.tf`).

## 구축 순서 (요약)

1. `oci/`: `terraform.tfvars`(저장소 제외)에 `tenancy_ocid`, `admin_ssh_public_key` → `tofu plan` → 확인 후 `tofu apply`.
2. 각 VM: `infra/`를 `/tmp/ject-infra`로 복사 → `sudo bash bootstrap-host.sh <role>` → `sudo bash install-role.sh <role>`.
3. 데이터 VM: `setup-secrets.sh prod-data` → `/srv/ject/data.env`에 `DATA_BIND_IP=<사설IP>` → `docker compose -p ject-prod-data -f /opt/ject/compose/prod-data.yaml --env-file /srv/ject/data.env up -d --wait`.
4. 앱 VM: 데이터 VM의 앱 DB·Redis 비밀값을 표준입력으로 `setup-secrets.sh prod-app-env <데이터 사설IP>`에 전달(화면 출력 없음) → `render-nginx.sh edge` → `ject-edge` 기동 → `ject-deploy deploy prod be <image@digest>`.
5. 개발 VM: `setup-secrets.sh dev`, `dev-app-env` → `ject-dev-data`, `ject-dev-gateway` 기동 → `ject-deploy deploy dev be ...`. 운영 Nginx의 `DEV_UPSTREAM=<개발 사설IP>:8080`.
5-1. CI: 환경별 배포 키 공개키를 `ject-deploy-key install <pub> <Bastion 사설 IP>`(운영 앱·개발 VM) → GitHub Environment 비밀값(`github-workflows/README.md`).
6. 도메인이 생기면 `/srv/ject/app/edge.env`에 `PROD_DOMAIN`, `DEV_DOMAIN` → DNS A 레코드 → `ject-cert issue`.
7. 백업: `systemctl start ject-pg-backup` → `ject-pg-restore-test latest` 성공 확인.

## 로컬 검증

```sh
colima start --cpu 2 --memory 3
colima ssh -- sudo bash "$PWD/infra/tests/local-e2e.sh"
```
OCI 대신 `tests/fake-oci.py`를 쓰므로, 실제 버킷·인스턴스 주체 권한은 서버에서 따로 검증한다.
