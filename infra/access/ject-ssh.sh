#!/usr/bin/env bash
# OCI Bastion 포트 포워딩 세션을 만들고 JECT VM에 본인 리눅스 계정으로 접속한다.
#   ject-ssh.sh <리눅스 사용자명> <prod-app|prod-data|dev> [명령...]
# A1(ARM) + Ubuntu VM은 Bastion 관리형 SSH 세션을 지원하지 않는다(OCI Bastion 알려진 문제).
# 그래서 Bastion은 VM의 22번까지 터널만 열고, 로그인은 VM에 등록된 본인 공개키로 한다.
# 필요: OCI CLI 로그인(세션 토큰 또는 API 키), ~/.config/ject/access.env (관리자가 전달하는 OCID 목록:
#   JECT_BASTION_ID, JECT_PROD_APP_ID/IP, JECT_PROD_DATA_ID/IP, JECT_DEV_ID/IP)
# 환경: OCI_PROFILE(기본 DEFAULT), OCI_AUTH(기본 security_token), SSH_KEY(기본 ~/.ssh/id_ed25519)
#       JECT_SESSION_ID: 이미 ACTIVE인 같은 대상 세션을 재사용(세션 생성 생략)
#       JECT_SSH_ARGS: 접속 대상 앞에 넣을 ssh 옵션(예: Grafana 터널 "-N -L 3000:127.0.0.1:3000")
#       JECT_KNOWN_HOSTS: VM 호스트 키 파일(기본 ~/.config/ject/known_hosts, 관리자가 access.env와 함께 전달).
#         파일이 있으면 호스트 키를 엄격히 확인하고, 없으면 처음 본 키를 그 파일에 저장한다.
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

SID="${JECT_SESSION_ID:-}"
if [ -z "$SID" ]; then
  SID=$(oci bastion session create-port-forwarding --bastion-id "$JECT_BASTION_ID" \
    --target-resource-id "$INST" --target-private-ip "$IP" --target-port 22 \
    --ssh-public-key-file "$KEY.pub" --session-ttl 10800 --display-name "$USER_NAME-$TARGET" \
    --query 'data.id' --raw-output)
  st=""
  for _ in $(seq 1 60); do
    st=$(oci bastion session get --session-id "$SID" --query 'data."lifecycle-state"' --raw-output 2>/dev/null || echo PENDING)
    [ "$st" = ACTIVE ] && break
    [[ "$st" =~ ^(FAILED|DELETED|DELETING)$ ]] && { echo "세션 실패: $st" >&2; exit 1; }
    sleep 5
  done
  [ "$st" = ACTIVE ] || { echo "세션 대기 시간 초과" >&2; exit 1; }
  echo "세션 준비됨(3시간, 재사용: JECT_SESSION_ID=$SID). 접속: $USER_NAME@$TARGET ($IP)" >&2
fi
KNOWN="${JECT_KNOWN_HOSTS:-$(dirname "$CONF")/known_hosts}"
if [ -s "$KNOWN" ]; then STRICT=yes; else STRICT=accept-new; fi
BASTION_KNOWN="$(dirname "$KNOWN")/bastion_known_hosts"
# 세션이 ACTIVE가 된 직후에는 터널이 잠시 실패할 수 있어 ssh 연결 오류(255)만 몇 번 다시 시도한다.
for attempt in 1 2 3 4 5; do
  rc=0
  ssh -i "$KEY" -o IdentitiesOnly=yes -o ConnectTimeout=20 \
    -o UserKnownHostsFile="$KNOWN" -o StrictHostKeyChecking="$STRICT" \
    -o ProxyCommand="ssh -i $KEY -o IdentitiesOnly=yes -o UserKnownHostsFile=$BASTION_KNOWN -o StrictHostKeyChecking=accept-new -W %h:%p -p 22 $SID@host.bastion.$REGION.oci.oraclecloud.com" \
    ${JECT_SSH_ARGS:-} "$USER_NAME@$IP" "$@" || rc=$?
  [ "$rc" -eq 255 ] && [ "$attempt" -lt 5 ] && [ $# -gt 0 ] || exit "$rc"
  echo "ssh 연결 재시도($attempt)" >&2; sleep 10
done
