# Trip-Sheet-5th-Infra

Trip Sheet(JECT 5기 3팀) 서버 인프라 코드입니다.

## 구성

| 서버 | 하는 일 |
| --- | --- |
| 운영 앱 서버 (`ject-prod-app`) | Nginx(HTTPS), 운영 BE |
| 운영 DB 서버 (`ject-prod-data`) | PostgreSQL 17, Redis 7.4, 매일 새벽 4시 백업 |
| 개발 + 모니터링 서버 (`ject-dev`) | 개발 BE·DB, Prometheus·Loki·Grafana, 장애 알림 |

세 대 모두 OCI Ampere A1 1코어·6GB·50GB이고 무료 한도 안에서 운영합니다.

배포는 앱 저장소([Trip-Sheet-5th-Server](https://github.com/JECT-Study/Trip-Sheet-5th-Server))에서 시작합니다.
GitHub Actions가 ARM64 이미지를 만들어 GHCR에 올리고, 개발 서버에는 자동으로, 운영 서버에는 개발에서 확인된 이미지만 수동으로 배포합니다.
배포 뒤 상태 확인에 실패하면 이전 버전으로 자동 복구합니다.

지금 서버에는 배포 경로 확인용 스모크 앱이 떠 있습니다. 앱 저장소에 CD를 붙이면 실제 앱으로 바뀝니다.

## 폴더

| 경로 | 내용 |
| --- | --- |
| `infra/oci/` | OCI 자원(OpenTofu): 네트워크, 서버, Bastion, 버킷, 권한, 알람 |
| `infra/scripts/` | 서버 설치, 배포(`ject-deploy`), 백업·복원 시험, 인증서, 계정 관리 |
| `infra/compose/` | 서버별 Docker Compose |
| `infra/nginx/` | Nginx 기본 설정(서버별 설정은 `scripts/render-nginx.sh`가 만든다) |
| `infra/observability/` | Prometheus·Loki·Alloy·Grafana 설정과 알림 규칙 |
| `infra/github-workflows/` | 앱 저장소에 넣을 빌드·배포 워크플로(이 저장소에서는 실행되지 않음) |
| `infra/access/` | 서버 접속 방법(Tailscale)과 팀원 계정 |
| `infra/tests/` | 로컬 통합 시험 |

운영 방법은 [`infra/README.md`](infra/README.md), 접속은 [`infra/access/README.md`](infra/access/README.md)에 있습니다.

## 서버 접속

필요한 사람만 Tailscale로 접속합니다. SSH 공개키와 Tailscale 초대받을 이메일을 인프라 담당에게 보내 주세요.
접속하지 않아도 개발·배포에는 지장 없습니다.

## 저장소에 넣지 않는 것

비밀값, IP, OCID, OpenTofu 상태 파일은 넣지 않습니다. 비밀값은 서버 안에서 만들고, CI에 필요한 값은 GitHub Environment에만 둡니다.
