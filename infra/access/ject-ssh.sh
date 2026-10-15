#!/usr/bin/env bash
# OCI Bastion 관리형 SSH 세션을 만들고 JECT VM에 접속한다.
#   ject-ssh.sh <리눅스 사용자명> <prod-app|prod-data|dev> [명령...]
# 필요: OCI CLI 로그인(세션 토큰 또는 API 키), ~/.config/ject/access.env (관리자가 전달하는 OCID 목록:
#   JECT_BASTION_ID, JECT_PROD_APP_ID/IP, JECT_PROD_DATA_ID/IP, JECT_DEV_ID/IP)
# 환경: OCI_PROFILE(기본 DEFAULT), OCI_AUTH(기본 security_token), SSH_KEY(기본 ~/.ssh/id_ed25519)
set -euo pipefail
USER_NAME="${1:?username}"; TARGET="${2:?prod-app|prod-data|dev}"; shift 2
CONF="${JECT_ACCESS_ENV:-$HOME/.config/ject/access.env}"
# shellcheck disable=SC1090
. "$CONF"
KEY="${SSH_KEY:-$HOME/.ssh/id_ed25519}"
REGION="${OCI_REGION:-ap-chuncheon-1}"
case "$TARGET" in
  prod-app)  INST="$JECT_PROD_APP_ID";  IP="$JECT_PROD_APP_IP" ;;
  prod-data) INST="$JECT_PROD_DATA_ID"; IP="$JECT_PROD_DATA_IP" ;;
  dev)       INST="$JECT_DEV_ID";       IP="$JECT_DEV_IP" ;;
  *) echo "대상 오류" >&2; exit 2 ;;
esac
oci() { command oci --profile "${OCI_PROFILE:-DEFAULT}" --auth "${OCI_AUTH:-security_token}" "$@"; }

SID=$(oci bastion session create-managed-ssh --bastion-id "$JECT_BASTION_ID" --target-resource-id "$INST" \
  --target-os-username "$USER_NAME" --target-private-ip "$IP" --ssh-public-key-file "$KEY.pub" \
  --session-ttl 10800 --display-name "$USER_NAME-$TARGET" --query 'data.id' --raw-output)
for _ in $(seq 1 60); do
  st=$(oci bastion session get --session-id "$SID" --query 'data."lifecycle-state"' --raw-output)
  [ "$st" = ACTIVE ] && break
  [[ "$st" =~ ^(FAILED|DELETED|DELETING)$ ]] && { echo "세션 실패: $st" >&2; exit 1; }
  sleep 5
done
[ "$st" = ACTIVE ] || { echo "세션 대기 시간 초과" >&2; exit 1; }
echo "세션 준비됨(3시간). 접속: $USER_NAME@$TARGET ($IP)" >&2
exec ssh -i "$KEY" -o ProxyCommand="ssh -i $KEY -W %h:%p -p 22 $SID@host.bastion.$REGION.oci.oraclecloud.com" "$USER_NAME@$IP" "$@"
