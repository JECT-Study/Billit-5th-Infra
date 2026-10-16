# 앱 저장소로 배포 워크플로 옮기기

이 폴더의 워크플로는 `ghdtjdwn/ject-infra`(비공개, 검증용)에서 스모크 이미지로 실제 실행·검증했다(2026-10-15).
실제 앱 저장소 `JECT-Study/Trip-Sheet-5th-Server`(공개)에는 2026-10-16 박상혁이 초기 코드를 올렸다(`develop` 기본 브랜치, `18fcc8b`).
성주의 권한은 읽기뿐이다. CI는 상혁이 만들고, 성주는 PR이 올라오면 CD를 붙이면서 맞춘다(2026-10-16 분담).
서버 쪽 코드(이 폴더가 든 `infra/`)의 원본은 팀 조직 저장소 `JECT-Study/Trip-Sheet-5th-Infra`(비공개)다. 앱 저장소에는 워크플로와 Dockerfile만 들어간다.

## 1. 앱 저장소에 맞출 것 (초기 코드 `18fcc8b` 기준)

| 항목 | 지금 앱 저장소 | 배포에 필요한 것 |
| --- | --- | --- |
| Dockerfile | 없음 | ARM64 이미지, `HEALTHCHECK`, 루트가 아닌 사용자(UID 65532), 포트 8080. `templates/backend/Dockerfile` 참고 |
| 상태 확인 | 없음 | `GET /readyz`(DB 연결 확인, 200/503). `ject-deploy`와 Nginx가 본다. Redis는 앱이 쓰기 시작할 때 추가 |
| 지표 | Actuator 없음 | 관리 포트 8081의 `/actuator/prometheus`. 없으면 「앱 지표 끊김」 알림이 계속 뜬다 |
| 프로필 | `local`·`test`·`release`·`prod`(`dev` 없음, `SPRING_PROFILES_ACTIVE`로 고름) | 서버는 지금 `APP_ENV=dev|prod`만 넣는다. 개발 VM은 `release`, 운영은 `prod`를 넣게 compose를 고친다 |
| DB 접속값 | `DB_URL`·`DB_USERNAME`·`DB_PASSWORD`(기본값 없음) | 서버 env 파일에는 `SPRING_DATASOURCE_*`와 `DB_USER`가 있다. `setup-secrets.sh`에 세 이름을 추가한다 |
| Redis | 의존성 없음 | 서버에는 준비돼 있다. 쓰기 시작할 때 연결 설정(`REDIS_HOST`·`REDIS_PORT`·`/run/secrets/redis_password`) |
| CI | `.github/workflows/ci.yml`: PR과 `main` push. `spotlessCheck test` + 스키마 문서 검사, DB는 Testcontainers | 우리 `gradle-check.yml`은 옮기지 않는다. CD는 `develop` push에서 도는 것으로 짜 두었다(브랜치는 팀 결정 전). `ci.yml`을 CD 앞에 붙일지는 PR 때 상혁과 정한다 |
| 개발 서버 자원 | — | 개발 BE는 `cpus: 0.30`, 메모리 1,024MiB(heap 50%). 실제 Spring 앱이 배포 대기 180초 안에 뜨는지 첫 배포 때 보고, 모자라면 `dev-app.yaml`을 올린다 |

## 2. 필요한 권한 (조직 관리자·저장소 관리자에게 요청)

| 필요한 것 | 누가 | 이유 |
| --- | --- | --- |
| 저장소 **admin**(또는 maintain + Environments 관리) | JECT-Study 조직 관리자 → 성주(또는 BE 리더) | Environment(`development`, `production`) 생성, 비밀값·변수 입력, 보호 규칙 설정 |
| 조직의 GitHub Packages 생성 허용 | 조직 관리자 | `ghcr.io/ject-study/<이미지>` 푸시(GITHUB_TOKEN `packages: write`) |
| Actions 허용 정책에 `docker/*` 액션 포함 | 조직 관리자 | `build-arm64.yml`이 `docker/setup-buildx-action`, `docker/login-action`, `docker/build-push-action`을 쓴다. 막혀 있으면 시작 단계에서 실패(startup_failure)한다 |
| (권장) `production` Environment Required reviewers | 저장소 admin | 공개 저장소는 무료로 쓸 수 있다. 운영 배포 승인자 지정 |
| `develop`·`main` 보호 규칙: PR 필수 + 필수 검사(`ci.yml`의 `verify`) 통과 | 저장소 admin | 2026-10-17 확인 시 규칙이 없어 CI가 실패해도 머지된다. 흐름도의 「통과해야 머지」가 실제로 되려면 필요하다 |

공개 저장소라 `ubuntu-24.04-arm` ARM64 러너를 무료로 쓴다. `build-arm64.yml`의 기본값이 이미 이 러너라 바꿀 것이 없다. 검증 저장소는 비공개라 QEMU로 빌드했고 개발 반영까지 약 10분 걸렸다.

## 3. 옮길 파일

| 이 폴더 | 앱 저장소 | 바꿀 곳 |
| --- | --- | --- |
| `build-arm64.yml` | `.github/workflows/build-arm64.yml` | 없음 |
| `deploy-via-bastion.yml` | `.github/workflows/deploy-via-bastion.yml` | 없음 |
| `ci-cd.yml` | `.github/workflows/cd.yml` 등 | `check` 잡은 앱 저장소 CI에 맞춘다(위 1절). `image_name`은 `ject-be`(서버가 `ghcr.io/ject-study/ject-`로 시작하는 이미지만 받는다) |

## 4. 서버 쪽 변경

- `/etc/ject/deploy.conf`의 `ALLOWED_IMAGE_PREFIX`를 `ghcr.io/ject-study/ject-`로 바꾼다(운영 앱 VM·개발 VM 둘 다).
- 프로필·DB 환경변수(위 1절)를 compose와 `setup-secrets.sh`에 반영한다.
- 이미지가 조직의 **비공개** 패키지면 지금처럼 배포 순간 `GITHUB_TOKEN`으로만 로그인한다(서버에 장기 자격증명 없음). 공개 패키지면 로그인 없이 받는다.

## 5. Environment 비밀값·변수 (development, production 각각)

`ghdtjdwn/ject-infra`에 넣은 것과 같은 이름이다. 값은 관리자 맥의 `~/.config/ject/access.env`와 CI 키에서 다시 만든다.

| 종류 | 이름 | 값 |
| --- | --- | --- |
| secret | `OCI_CLI_USER` | `ject-ci-dev-bot` / `ject-ci-prod-bot` 사용자 OCID |
| secret | `OCI_CLI_TENANCY` | 테넌시 OCID |
| secret | `OCI_CLI_FINGERPRINT`, `OCI_CLI_KEY_CONTENT` | 그 사용자의 API 키 지문과 개인키(PEM, 끝 줄 `OCI_API_KEY`) |
| secret | `JECT_DEPLOY_SSH_KEY` | 환경별 배포 SSH 개인키(서버 `deploy` 계정에 공개키 등록, `ject-deploy-key install`) |
| var | `OCI_CLI_REGION` | `ap-chuncheon-1` |
| var | `JECT_BASTION_ID`, `JECT_INSTANCE_ID`, `JECT_PRIVATE_IP` | Bastion OCID, 대상 VM OCID·사설 IP(개발=`ject-dev-obs`, 운영=`ject-prod-app`) |
| var | `JECT_HOST_KEY` | 대상 VM의 `ssh-ed25519 AAAA...` 호스트 키 |
| var | `JECT_IMAGE_PREFIX` | `ghcr.io/ject-study/ject-` |

개인키는 GitHub에서 다시 읽을 수 없다. 옮길 때는 **새 키를 만들어** 앱 저장소에 넣고(`oci iam user api-key upload`, `ject-deploy-key install`),
`ghdtjdwn/ject-infra`의 옛 키는 OCI에서 삭제한다(`oci iam user api-key delete`).

## 6. 검증 순서 (ject-infra에서 실제로 한 것과 같음)

1. 개발 브랜치 push → 빌드 → 개발 자동 배포 → 커밋에 `ject/dev-verified`(digest)
2. 수동 실행 `environment=prod action=deploy image=<digest> commit=<sha>` → 운영 승격
3. 한 번 더 승격한 뒤 `action=rollback` → 직전 이미지로 복귀
4. 검증 안 된 digest를 운영에 넣으면 거부되는지 확인

같은 환경 배포는 GitHub `concurrency`로 하나씩만 돈다. 실행 중에 두 번 더 들어오면 GitHub가 중간 것을 취소하고 마지막 것만 이어서 돌린다.

## 참고: gradle-check.yml

ject-infra에서 쓴 검사 워크플로다(PR·push마다 `spotlessCheck test build`, PostgreSQL·Redis 서비스 컨테이너). 앱 저장소에는 상혁의 `ci.yml`이 있어서 옮기지 않는다.

## 옮길 때 같이 정할 것: CI 접속을 Tailscale로 바꿀지

지금 CI는 OCI Bastion 포트 포워딩으로 들어오고, 사람은 Tailscale로 들어온다. 앱 저장소로 옮길 때는 어차피 OCI API 키를 새로 만들어야 한다(5절).
그때 CI도 Tailscale로 바꾸면 OCI 로봇 계정 2개, CI용 IAM 정책, Bastion 세션 생성·대기·재시도 코드가 빠지고 Bastion 동시 세션 한도와도 무관해진다.

- 할 일: Tailscale 콘솔에서 `tag:ci` OAuth 클라이언트 생성, 정책에 `tag:ci` → `tag:ject` `tcp:22` 추가 → 워크플로에서 `tailscale/github-action`으로 접속 →
  `deploy` 계정 키의 `from=`을 Bastion IP에서 Tailscale 대역(`100.64.0.0/10`)으로 바꾼다(`ject-deploy-key`).
- 대가: 배포까지 성주 개인 tailnet에 기댄다. 무료 Personal 요금제는 비상업용이다(동아리 프로젝트는 해당).
- 정하기 전까지는 지금 방식(Bastion)을 그대로 쓴다. 검증된 경로다.
