# ject-infra (검증용)

**인프라 코드 원본은 팀 저장소 [`JECT-Study/Trip-Sheet-5th-Infra`](https://github.com/JECT-Study/Trip-Sheet-5th-Infra)다(2026-10-17부터).**
이 저장소는 스모크 앱으로 배포 파이프라인을 시험하는 사본이라 `.github/workflows`와 `spring-sample`이 더 있다. `infra/`는 두 저장소에 같이 반영하고, CD를 앱 저장소로 옮기면 이 저장소는 보관(archive)한다.

JECT 5기 3팀 인프라 코드와 배포 파이프라인 검증 저장소. `infra/smoke-app`은 실제 서비스가 아니라
ARM64 빌드 → GHCR → OCI Bastion(포트 포워딩) → ject-deploy 배포·자동 복구·롤백 경로를 확인하기 위한 최소 이미지다.
실제 앱 저장소가 생기면 `infra/github-workflows`의 워크플로를 그 저장소의 `.github/workflows`로 옮긴다.
비밀값·IP·OCID는 저장소에 두지 않는다(GitHub Environment 비밀값/변수로만 둔다).

## 워크플로

| 파일 | 용도 |
| --- | --- |
| `ci-cd.yml` | main push: ARM64 빌드 → GHCR → 개발 VM 자동 배포 → 커밋에 `ject/dev-verified`(digest). 수동 실행: 운영 승격(개발 검증 digest만)·롤백 |
| `build-arm64.yml` | 재사용: linux/arm64 이미지 빌드·푸시, digest 출력 |
| `deploy-via-bastion.yml` | 재사용: Bastion 포트 포워딩 세션 → deploy 계정(강제 명령 ject-deploy-gate) → `ject-deploy` |
| `e2e-broken-deploy.yml` | 검증 전용: readiness가 실패하는 `-broken` 이미지를 개발에 배포해 자동 복구를 확인(실행 결과는 "실패"가 정상) |

## Environment

`development`(개발 VM), `production`(운영 앱 VM). 둘 다 배포 브랜치는 `main`만 허용한다.
GitHub Free 비공개 저장소라 Required reviewers·wait timer는 쓸 수 없다. 운영 배포는 수동 실행(workflow_dispatch)과
개발 검증 digest 확인으로만 막는다.
