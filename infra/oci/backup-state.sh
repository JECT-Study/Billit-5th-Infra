#!/usr/bin/env bash
# OpenTofu 상태 파일을 비공개 버킷 ject-tfstate에 올린다. tofu apply 뒤에 실행한다.
#   bash infra/oci/backup-state.sh
# 상태 파일은 관리자 PC에만 있어서, 잃으면 자원을 하나씩 tofu import로 다시 맞춰야 한다.
# 버킷은 버전 관리를 켜 두어 이전 판이 남고, 서버(인스턴스 주체)와 팀원 그룹에는 객체 권한이 없다.
# 되찾기: oci os object get -bn ject-tfstate --name terraform.tfstate --file terraform.tfstate
# 환경: OCI_PROFILE(기본 DEFAULT), OCI_AUTH(기본 security_token)
set -euo pipefail
cd "$(dirname "$0")"
oci() { command oci --profile "${OCI_PROFILE:-DEFAULT}" --auth "${OCI_AUTH:-security_token}" "$@"; }
python3 -c 'import json,sys; s=json.load(open("terraform.tfstate")); sys.exit(0 if s["resources"] else 1)' \
  || { echo "terraform.tfstate가 비었거나 읽을 수 없다 — 올리지 않음" >&2; exit 1; }
ns=$(oci os ns get --query data --raw-output)
for f in terraform.tfstate terraform.tfvars *.auto.tfvars; do
  [ -f "$f" ] || continue
  oci os object put -ns "$ns" -bn ject-tfstate --name "$f" --file "$f" --force >/dev/null
  echo "올림: $f"
done
