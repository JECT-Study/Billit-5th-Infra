#!/usr/bin/env bash
# 팀원 ssh는 Tailscale로 들어온다. 서버를 tag:ject로 넣는다(키 만료 없음).
# 누가 어디에 붙을 수 있는지는 Tailscale 콘솔의 정책이 정한다(팀원은 tag:ject의 22만).
#   sudo bash install-tailscale.sh          설치하고 로그인 시작. 승인 링크를 출력한다
#   sudo bash install-tailscale.sh status
set -euo pipefail
[ "$(id -u)" -eq 0 ] || { echo "root로 실행" >&2; exit 1; }
ROLE="$(cat /etc/ject/role)"
case "$ROLE" in prod-app) NAME=ject-prod-app ;; prod-data) NAME=ject-prod-data ;; dev) NAME=ject-dev ;; *) exit 2 ;; esac

if [ "${1:-}" = status ]; then tailscale status --self --peers=false; tailscale ip -4; exit 0; fi

if ! command -v tailscale >/dev/null 2>&1; then
  . /etc/os-release
  curl -fsSL "https://pkgs.tailscale.com/stable/ubuntu/${VERSION_CODENAME}.noarmor.gpg" -o /usr/share/keyrings/tailscale-archive-keyring.gpg
  curl -fsSL "https://pkgs.tailscale.com/stable/ubuntu/${VERSION_CODENAME}.tailscale-keyring.list" -o /etc/apt/sources.list.d/tailscale.list
  apt-get update -y >/dev/null
  DEBIAN_FRONTEND=noninteractive apt-get install -y tailscale >/dev/null
fi
systemctl enable --now tailscaled >/dev/null

if tailscale status >/dev/null 2>&1; then echo "이미 로그인됨: $(tailscale ip -4)"; exit 0; fi
# DNS는 OCI 것 그대로, Tailscale SSH는 안 쓴다(일반 sshd + 개인 공개키).
nohup tailscale up --hostname="$NAME" --advertise-tags=tag:ject --accept-dns=false --ssh=false \
  > /var/log/ject-tailscale-up.log 2>&1 &
for _ in $(seq 1 20); do grep -q "https://login.tailscale.com" /var/log/ject-tailscale-up.log && break; sleep 1; done
grep -o "https://login.tailscale.com[^ ]*" /var/log/ject-tailscale-up.log | head -1
