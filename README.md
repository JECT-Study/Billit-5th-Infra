# Billit-5th-Infra

Billit의 OCI 서버 구성과 공통 배포 워크플로를 관리합니다.

## 서버 구성

| 서버 | 역할 |
| --- | --- |
| 운영 앱 (`ject-prod-app`) | Nginx, 백엔드, 웹 배포 환경 |
| 운영 데이터 (`ject-prod-data`) | PostgreSQL 17, Redis 7.4, DB 백업 |
| 개발 (`ject-dev`) | 개발 앱·DB, Prometheus·Loki·Grafana |

서버는 각각 OCI Ampere A1 1 OCPU, 메모리 6GB, 디스크 50GB를 사용합니다.
현재 배포 확인용 앱을 실행 중이며, 실제 BE·FE 앱 연결은 준비 중입니다.

## 배포

앱 저장소에서 검사 후 공통 워크플로를 호출합니다.

1. ARM64 이미지를 빌드해 GHCR에 저장합니다.
2. 개발 서버에 배포하고 상태를 확인합니다.
3. 개발에서 확인한 이미지를 운영 서버에 수동 배포합니다.

배포 후 상태 검사에 실패하면 이전 이미지로 복구합니다. 이 저장소의 워크플로는 `workflow_call` 전용입니다.
연결 방법과 필요한 설정은 [배포 가이드](infra/github-workflows/README.md)를 참고하세요.

## 디렉터리

| 경로 | 내용 |
| --- | --- |
| `infra/oci/` | OpenTofu 네트워크·서버·스토리지·권한 설정 |
| `infra/scripts/` | 서버 설치, 배포, 백업·복원, 인증서 관리 |
| `infra/compose/` | 서버별 Docker Compose 설정 |
| `infra/nginx/` | Nginx 기본 설정 |
| `infra/observability/` | 지표·로그 수집, 대시보드, 알림 |
| `.github/workflows/` | 공통 빌드·배포 워크플로 |
| `infra/github-workflows/` | 워크플로 사본과 앱 저장소 호출 예시 |
| `infra/access/` | SSH 접속과 계정 관리 |
| `infra/tests/` | 배포·백업·모니터링 통합 시험 |

## 운영 문서

- [서버 구성과 운영](infra/README.md)
- [서버·DB 접속](infra/access/README.md)
- [앱 배포 연결](infra/github-workflows/README.md)
- [백엔드 저장소](https://github.com/JECT-Study/Billit-5th-Server)
- [프론트엔드 저장소](https://github.com/JECT-Study/Billit-5th-Client)

서버 접속은 Tailscale과 개인 SSH 키를 사용합니다. 계정이 필요하면 인프라 담당에게 공개키와 초대받을 이메일을 전달하세요.
비밀값과 OpenTofu 상태 파일은 저장소에 포함하지 않습니다.
