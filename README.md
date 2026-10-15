# ject-infra (검증용)

JECT 5기 3팀 인프라 코드와 배포 파이프라인 검증 저장소. `infra/smoke-app`은 실제 서비스가 아니라
ARM64 빌드 → GHCR → OCI Bastion 배포 → 롤백 경로를 확인하기 위한 최소 이미지다.
실제 앱 저장소가 생기면 `.github/workflows`를 그 저장소로 옮긴다. 비밀값·IP·OCID는 저장소에 두지 않는다
(GitHub Environment 비밀값/변수로만 둔다).
