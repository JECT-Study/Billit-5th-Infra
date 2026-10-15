# 앱 저장소로 배포 워크플로 옮기기

이 폴더의 워크플로는 `ghdtjdwn/ject-infra`(비공개, 검증용)에서 스모크 이미지로 실제 실행·검증했다(2026-10-15).
실제 JECT 앱 저장소 `JECT-Study/Trip-Sheet-5th-Server`는 2026-10-15 기준 **비어 있고(공개 저장소)**, 성주의 권한은 `pull`뿐이다.
앱 코드가 들어오면 아래 순서로 옮긴다. 상태는 `docs/인프라-설계.md`의 「구축 결과」를 본다.

## 1. 필요한 권한 (조직 관리자·저장소 관리자에게 요청)

| 필요한 것 | 누가 | 이유 |
| --- | --- | --- |
| 저장소 **admin**(또는 maintain + Environments 관리) | JECT-Study 조직 관리자 → 성주(또는 BE 리더) | Environment(`development`, `production`) 생성, 비밀값·변수 입력, 보호 규칙 설정 |
| 조직의 GitHub Packages 생성 허용 | 조직 관리자 | `ghcr.io/ject-study/<이미지>` 푸시(GITHUB_TOKEN `packages: write`) |
| Actions 허용 정책에 `docker/*`, `gradle/actions/*` 액션 포함 | 조직 관리자 | `build-arm64.yml`이 `docker/setup-buildx-action`, `docker/login-action`, `docker/build-push-action`, `gradle-check.yml`이 `gradle/actions/setup-gradle`(+ `actions/setup-java`, `actions/upload-artifact`) 사용. 막혀 있으면 시작 단계에서 실패(startup_failure)한다 |
| (권장) `production` Environment Required reviewers | 저장소 admin | 공개 저장소는 무료로 쓸 수 있다. 운영 배포 승인자 지정 |

공개 저장소이므로 `ubuntu-24.04-arm` ARM64 러너를 무료로 쓸 수 있다(빌드가 QEMU보다 빠르다). 비공개라면 `runner: ubuntu-24.04`(QEMU)로 바꾼다.

## 2. 옮길 파일

| 이 폴더 | 앱 저장소 | 바꿀 곳 |
| --- | --- | --- |
| `build-arm64.yml` | `.github/workflows/build-arm64.yml` | 없음 |
| `deploy-via-bastion.yml` | `.github/workflows/deploy-via-bastion.yml` | 없음 |
| `gradle-check.yml` | `.github/workflows/gradle-check.yml` | 없음(Gradle 프로젝트가 저장소 루트가 아니면 `working_directory`) |
| `ci-cd.yml` | `.github/workflows/ci-cd.yml` | `push.branches`를 팀 개발 통합 브랜치로, `image_name`을 실제 이미지 이름(예: `ject-be`)으로. `check`는 이미 `gradle-check.yml`(spotlessCheck·test·build)을 부르고, push 때 build가 check 뒤에 돈다 |

앱 이미지 조건: ARM64, 컨테이너 `HEALTHCHECK`, `GET /readyz`(DB·Redis 연결 확인, 200/503), 8080 포트, 루트가 아닌 사용자.
UID가 65532가 아니면 서버의 `APP_UID`로 `setup-secrets.sh prod-app-env`/`dev-app-env`를 다시 실행해 Redis 비밀번호 파일 소유자를 맞춘다.

## 3. 서버 쪽 변경

- `/etc/ject/deploy.conf`의 `ALLOWED_IMAGE_PREFIX`를 `ghcr.io/ject-study/ject-`(실제 이미지 접두사)로 바꾼다(운영 앱 VM·개발 VM 둘 다).
- 이미지가 조직의 **비공개** 패키지면 지금처럼 배포 순간 `GITHUB_TOKEN`으로만 로그인한다(서버에 장기 자격증명 없음). 공개 패키지면 로그인 없이 받는다.

## 4. Environment 비밀값·변수 (development, production 각각)

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

## 4-1. CI 검사(gradle-check.yml)

- PR·push마다 `./gradlew --no-daemon spotlessCheck test build`. 비밀값을 쓰지 않는다(포크 PR에서도 돈다).
- 서비스 컨테이너: PostgreSQL 17.11(`ject`/`ject`, 호스트 15432)·Redis 7.4.11(16379) — 로컬 `compose.yaml`과 같아서 `local` 프로필 그대로 테스트가 붙는다.
- 실패하면 `test-reports` 아티팩트(7일). `setup-gradle`이 wrapper 체크섬을 검증하고 Gradle 캐시를 쓴다.
- 2026-10-15 `ghdtjdwn/ject-infra`의 `e2e-spring-sample`(check → build → 개발 배포)로 실제 실행했다.

## 5. 검증 순서 (ject-infra에서 실제로 한 것과 같음)

1. 개발 브랜치 push → 빌드 → 개발 자동 배포 → 커밋에 `ject/dev-verified`(digest)
2. 수동 실행 `environment=prod action=deploy image=<digest> commit=<sha>` → 운영 승격
3. 한 번 더 승격한 뒤 `action=rollback` → 직전 이미지로 복귀
4. 검증 안 된 digest를 운영에 넣으면 거부되는지 확인
