# 공통 배포 워크플로 연결

이 폴더의 워크플로는 `ghdtjdwn/ject-infra`(비공개, 검증용)에서 스모크 이미지로 실제 실행·검증했다(2026-10-15).
실제 앱 저장소 `JECT-Study/Trip-Sheet-5th-Server`(공개)에는 2026-10-16 BE 리더가 초기 코드를 올렸다(`develop` 기본 브랜치, `18fcc8b`).
인프라 담당의 권한은 읽기뿐이다. CI는 BE 리더가 만들고, 인프라 담당은 PR이 올라오면 CD를 붙이면서 맞춘다(2026-10-16 분담).
서버 코드와 공통 빌드·배포는 `JECT-Study/Trip-Sheet-5th-Infra`에서 관리한다. 앱 저장소에는 서비스별 검사, 공통 워크플로를 호출하는 진입 파일, Dockerfile을 둔다.

공통 호출을 사용하려면 Infra 저장소 공개 전환, Actions 활성화, `.github/workflows/build-arm64.yml`·`deploy-via-bastion.yml` 반영이 필요하다. 현재 파일은 이 연결을 위한 준비이며 실제 앱 배포 완료를 뜻하지 않는다. 공개 앱 저장소는 비공개 Infra 워크플로를 직접 호출할 수 없다.

## 1. 앱 저장소에 맞출 것 (초기 코드 `18fcc8b` 기준)

| 항목 | 지금 앱 저장소 | 배포에 필요한 것 |
| --- | --- | --- |
| Dockerfile | 없음 | ARM64 이미지, `HEALTHCHECK`, 루트가 아닌 사용자(UID 65532), 포트 8080. `templates/backend/Dockerfile` 참고 |
| 상태 확인 | 없음 | `GET /readyz`(DB 연결 확인, 200/503). `ject-deploy`와 Nginx가 본다. Redis는 앱이 쓰기 시작할 때 추가 |
| 지표 | Actuator 없음 | 관리 포트 8081의 `/actuator/prometheus`. 없으면 「앱 지표 끊김」 알림이 계속 뜬다 |
| 프로필 | `local`·`test`·`release`·`prod`(`dev` 없음, `SPRING_PROFILES_ACTIVE`로 고름) | Compose에 개발 `SPRING_PROFILES_ACTIVE=release`, 운영 `prod`를 정의했다. 실제 서버 적용은 별도 |
| DB 접속값 | `DB_URL`·`DB_USERNAME`·`DB_PASSWORD`(기본값 없음) | `setup-secrets.sh`에 `DB_URL`·`DB_USERNAME`을 추가했고 `DB_PASSWORD`는 기존 값을 사용한다. 기존 서버 env 재생성은 별도 |
| Redis | 의존성 없음 | 서버에는 준비돼 있다. 쓰기 시작할 때 연결 설정(`REDIS_HOST`·`REDIS_PORT`·`/run/secrets/redis_password`) |
| CI | `.github/workflows/ci.yml`: PR과 `main` push. `spotlessCheck test` + 스키마 문서 검사, DB는 Testcontainers | 우리 `gradle-check.yml`은 옮기지 않는다. CD는 `develop` push에서 도는 것으로 짜 두었다(브랜치는 팀 결정 전). `ci.yml`을 CD 앞에 붙일지는 PR 때 BE 리더와 정한다 |
| 개발 서버 자원 | — | 개발 BE는 `cpus: 0.30`, 메모리 1,024MiB(heap 50%). 실제 Spring 앱이 배포 대기 180초 안에 뜨는지 첫 배포 때 보고, 모자라면 `dev-app.yaml`을 올린다 |

## 2. 필요한 권한 (조직 관리자·저장소 관리자에게 요청)

| 필요한 것 | 누가 | 이유 |
| --- | --- | --- |
| 저장소 **admin**(또는 maintain + Environments 관리) | JECT-Study 조직 관리자 → 인프라 담당(또는 BE 리더) | Environment(`development`, `production`) 생성, 비밀값·변수 입력, 보호 규칙 설정 |
| 조직의 GitHub Packages 생성 허용 | 조직 관리자 | `ghcr.io/ject-study/<이미지>` 푸시(GITHUB_TOKEN `packages: write`) |
| Actions 허용 정책에 `docker/*` 액션 포함 | 조직 관리자 | `build-arm64.yml`이 `docker/setup-buildx-action`, `docker/login-action`, `docker/build-push-action`을 쓴다. 막혀 있으면 시작 단계에서 실패(startup_failure)한다 |
| (권장) `production` Environment Required reviewers | 저장소 admin | 공개 저장소는 무료로 쓸 수 있다. 운영 배포 승인자 지정 |
| `develop`·`main` 보호 규칙: PR 필수 + 필수 검사(`ci.yml`의 `verify`) 통과 | 저장소 admin | 2026-10-17 확인 시 규칙이 없어 CI가 실패해도 머지된다. 흐름도의 「통과해야 머지」가 실제로 되려면 필요하다 |

공개 저장소라 `ubuntu-24.04-arm` ARM64 러너를 무료로 쓴다. `build-arm64.yml`의 기본값이 이미 이 러너라 바꿀 것이 없다. 검증 저장소는 비공개라 QEMU로 빌드했고 개발 반영까지 약 10분 걸렸다.

## 3. 공통 파일과 호출 파일

| 이 폴더 | 반영 위치 | 역할 |
| --- | --- | --- |
| `build-arm64.yml` | Infra의 `.github/workflows/build-arm64.yml` | `workflow_call`로만 실행하는 공통 ARM64 빌드 |
| `deploy-via-bastion.yml` | Infra의 `.github/workflows/deploy-via-bastion.yml` | `workflow_call`로만 실행하는 공통 배포·롤백 |
| `ci-cd.yml` | 각 앱 저장소의 `.github/workflows/cd.yml` 등 | 호출 예시. `check`는 해당 앱의 검사로 연결 |

`ci-cd.yml`의 `@main`은 예시다. 실제 연결할 때 검증한 Infra 커밋 SHA로 고정한다. 공통 코드를 고친 뒤 각 앱의 참조 SHA를 갱신해야 반영된다.
빌드 입력은 `context`, `dockerfile`, `image_name`, `extra_build_args`이며, FE 웹은 `image_name: ject-fe`, 배포 입력 `service: fe`를 사용한다. BE는 `ject-be`, `service: be`다.
비밀값과 `development`·`production` 환경의 승인·변수는 **호출하는 앱 저장소**에 둔다. 공통 배포 호출에는 `secrets: inherit`와 필요한 `permissions`를 전달한다.

Next.js 웹에서 같은 이미지를 개발·운영에 사용하려면 `NEXT_PUBLIC_*`에 환경별 API 주소를 빌드 시 고정하지 않는다. 같은 호스트의 `/api` 상대 경로 또는 런타임 설정을 사용한다. 웹 Dockerfile에는 상태 검사를 정의하고, 배포 후 `PROD_FE_UPSTREAM=fe:3000`·`DEV_FE_UPSTREAM=fe:3000`으로 Nginx를 연결한다. 웹은 OCI 배포로 확정됐다. 웹 컨테이너의 정상 배포를 확인한 뒤 Nginx 연결을 활성화한다.

Release 이벤트·버전 태그 생성은 이 예시에 포함하지 않는다. 현재 운영 진입점은 수동 실행이며, 릴리스 정책 확정 후 같은 digest에 태그를 붙이는 절차를 연결한다.

### FE 웹 호출 입력

FE 저장소의 검사 작업이 성공한 뒤 공통 빌드를 호출한다. Node 버전·패키지 매니저·검사 명령은 FE 저장소 설정을 따른다.

```yaml
build:
  needs: check
  permissions: { contents: read, packages: write }
  uses: JECT-Study/Trip-Sheet-5th-Infra/.github/workflows/build-arm64.yml@main
  with:
    image_name: ject-fe

deploy-dev:
  needs: build
  permissions: { contents: read, packages: read, statuses: write }
  uses: JECT-Study/Trip-Sheet-5th-Infra/.github/workflows/deploy-via-bastion.yml@main
  with:
    environment: dev
    service: fe
    image: ${{ needs.build.outputs.image }}
    commit: ${{ github.sha }}
  secrets: inherit
```

위 조각은 FE 진입 워크플로의 `jobs` 아래에 넣는다. PR에서는 배포하지 않고, 배포 브랜치 push에서만 실행되도록 진입 파일에 조건을 둔다. 운영 수동 호출에도 `service: fe`를 반드시 전달한다. 이 예시의 `@main`도 실제 연결 시 검증한 커밋 SHA로 바꾼다.

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

같은 저장소·환경·서비스의 실행은 GitHub `concurrency`로 조절한다. 서로 다른 앱 저장소의 배포는 이 설정을 공유하지 않으므로 서버의 환경별 잠금으로 순차 실행한다. 잠금은 기본 600초 대기하고, `DEPLOY_LOCK_TIMEOUT`으로 조절한다. 시간 초과 시 현재 이미지와 배포 이력은 변경하지 않는다.

## 참고: gradle-check.yml

ject-infra에서 쓴 검사 워크플로다(PR·push마다 `spotlessCheck test build`, PostgreSQL·Redis 서비스 컨테이너). 앱 저장소에는 자체 `ci.yml`이 있어서 옮기지 않는다.

## 옮길 때 같이 정할 것: CI 접속을 Tailscale로 바꿀지

지금 CI는 OCI Bastion 포트 포워딩으로 들어오고, 사람은 Tailscale로 들어온다. 앱 저장소로 옮길 때는 어차피 OCI API 키를 새로 만들어야 한다(5절).
그때 CI도 Tailscale로 바꾸면 OCI 로봇 계정 2개, CI용 IAM 정책, Bastion 세션 생성·대기·재시도 코드가 빠지고 Bastion 동시 세션 한도와도 무관해진다.

- 할 일: Tailscale 콘솔에서 `tag:ci` OAuth 클라이언트 생성, 정책에 `tag:ci` → `tag:ject` `tcp:22` 추가 → 워크플로에서 `tailscale/github-action`으로 접속 →
  `deploy` 계정 키의 `from=`을 Bastion IP에서 Tailscale 대역(`100.64.0.0/10`)으로 바꾼다(`ject-deploy-key`).
- 대가: 배포까지 인프라 담당 개인 tailnet에 기댄다. 무료 Personal 요금제는 비상업용이다(동아리 프로젝트는 해당).
- 정하기 전까지는 지금 방식(Bastion)을 그대로 쓴다. 검증된 경로다.
