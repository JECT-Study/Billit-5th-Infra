#!/usr/bin/env bash
# JECT VM 공통 설정. 여러 번 돌려도 된다.
#   sudo bash bootstrap-host.sh <prod-app|prod-data|dev>
# docker + compose, 로그 용량 제한, /srv/ject /opt/ject, deploy 계정, 무인 보안 업데이트, sshd 설정, motd
set -euo pipefail

ROLE="${1:-$(cat /etc/ject/role 2>/dev/null || true)}"
case "$ROLE" in prod-app|prod-data|dev) ;; *) echo "usage: $0 <prod-app|prod-data|dev>" >&2; exit 2;; esac
[ "$(id -u)" -eq 0 ] || { echo "root로 실행" >&2; exit 1; }
. /etc/os-release
[ "$VERSION_ID" = "24.04" ] || { echo "Ubuntu 24.04 전용 (현재 $VERSION_ID)" >&2; exit 1; }
[ "$(uname -m)" = "aarch64" ] || { echo "ARM64 전용" >&2; exit 1; }

export DEBIAN_FRONTEND=noninteractive
mkdir -p /etc/ject
echo "$ROLE" > /etc/ject/role

# ---- 패키지 ------------------------------------------------------------------
if ! command -v docker >/dev/null 2>&1; then
  apt-get update -y
  apt-get install -y ca-certificates curl gnupg jq python3-venv unattended-upgrades
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
  chmod a+r /etc/apt/keyrings/docker.asc
  echo "deb [arch=arm64 signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu ${VERSION_CODENAME} stable" \
    > /etc/apt/sources.list.d/docker.list
  apt-get update -y
  apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
fi
apt-get install -y jq python3-venv unattended-upgrades >/dev/null

# ---- Docker 데몬 설정 ----------------------------------------------------------
install -d -m 0755 /etc/docker
cat > /etc/docker/daemon.json.new <<'JSON'
{
  "log-driver": "json-file",
  "log-opts": { "max-size": "10m", "max-file": "3" },
  "live-restore": true,
  "userland-proxy": false,
  "default-address-pools": [ { "base": "172.30.0.0/16", "size": 24 } ]
}
JSON
if ! cmp -s /etc/docker/daemon.json.new /etc/docker/daemon.json 2>/dev/null; then
  if [ -n "$(docker ps -q 2>/dev/null)" ] && [ "${FORCE_DOCKER_RESTART:-0}" != 1 ]; then
    echo "실행 중인 컨테이너가 있어 Docker를 재시작하지 않는다. 확인 후 FORCE_DOCKER_RESTART=1로 재실행" >&2
    exit 1
  fi
  mv /etc/docker/daemon.json.new /etc/docker/daemon.json
  systemctl restart docker
else
  rm -f /etc/docker/daemon.json.new
fi
systemctl enable --now docker >/dev/null

# ---- journald 용량 제한 ----------------------------------------------------------
install -d /etc/systemd/journald.conf.d
cat > /etc/systemd/journald.conf.d/ject.conf <<'CONF'
[Journal]
SystemMaxUse=500M
MaxRetentionSec=14day
CONF
systemctl restart systemd-journald

# ---- 무인 보안 업데이트: 자동 재부팅은 하지 않는다 ------------------------------
cat > /etc/apt/apt.conf.d/52ject-unattended <<'CONF'
Unattended-Upgrade::Automatic-Reboot "false";
Unattended-Upgrade::Remove-Unused-Dependencies "true";
CONF

# ---- 디렉터리 ----------------------------------------------------------------
install -d -m 0755 /srv/ject /opt/ject /opt/ject/bin /var/log/ject
install -d -m 0700 /srv/ject/secrets
case "$ROLE" in
  prod-app)
    install -d -m 0755 /srv/ject/app /srv/ject/app/nginx /srv/ject/app/acme /srv/ject/app/releases
    install -d -m 0700 /srv/ject/certs ;;
  prod-data)
    install -d -m 0700 /srv/ject/data /srv/ject/data/postgres /srv/ject/data/redis /srv/ject/backup-tmp
    install -d -m 0755 /srv/ject/backup-status ;;
  dev)
    install -d -m 0755 /srv/ject/dev /srv/ject/dev/releases
    install -d -m 0700 /srv/ject/dev-data /srv/ject/dev-data/postgres /srv/ject/dev-data/redis ;;
esac

# ---- 그룹·배포 계정 ------------------------------------------------------------
getent group ject-admins >/dev/null || groupadd ject-admins
cat > /etc/sudoers.d/90-ject-admins <<'CONF'
%ject-admins ALL=(ALL) NOPASSWD:ALL
CONF
chmod 0440 /etc/sudoers.d/90-ject-admins

# deploy: CI가 Bastion 세션으로 접속하는 계정. docker 그룹에 넣지 않고
# 검증된 배포 명령 하나만 sudo로 허용한다.
if ! id deploy >/dev/null 2>&1; then
  useradd --create-home --shell /bin/bash --comment "JECT CI deploy" deploy
  passwd -l deploy >/dev/null
fi
install -d -m 0700 -o deploy -g deploy /home/deploy/.ssh
touch /home/deploy/.ssh/authorized_keys
chown deploy:deploy /home/deploy/.ssh/authorized_keys
chmod 0600 /home/deploy/.ssh/authorized_keys
cat > /etc/sudoers.d/91-ject-deploy <<'CONF'
deploy ALL=(root) NOPASSWD: /opt/ject/bin/ject-deploy
CONF
chmod 0440 /etc/sudoers.d/91-ject-deploy
visudo -cq

# ---- 로그인하면 보이는 안내 ---------------------------------------------------------
case "$ROLE" in
  prod-app)  WHAT="운영 앱 서버. nginx(https)랑 운영 BE 컨테이너가 돌아요."
             HOW="상태: sudo ject-deploy status prod" ;;
  prod-data) WHAT="운영 DB 서버. PostgreSQL, Redis, 새벽 4시 백업."
             HOW="백업 결과: cat /srv/ject/backup-status/last.json" ;;
  dev)       WHAT="개발 서버. 개발 BE/DB랑 모니터링(Grafana, Prometheus, Loki)."
             HOW="상태: sudo ject-deploy status dev / Grafana는 ssh -L 3000:127.0.0.1:3000 으로" ;;
esac
cat > /etc/motd <<CONF

 JECT 3팀 - $WHAT
   - 배포는 CI가 해요. docker compose 직접 올리고 내리지 말아 주세요
   - /srv/ject/secrets 는 열어보거나 복사하지 않기
   - $HOW
   - 이상하면 성주에게

CONF

# ---- SSH: 키 로그인만, ject-admins 그룹과 deploy만 ---------------------------------------
# 22는 Tailscale(tag:ject)과 Bastion에서만 들어온다. 인터넷에 열지 않는다.
cat > /etc/ssh/sshd_config.d/60-ject.conf <<'CONF'
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitRootLogin no
MaxAuthTries 3
AllowGroups ject-admins deploy
CONF
sshd -t && systemctl reload ssh


echo "bootstrap ok: role=$ROLE docker=$(docker --version | awk '{print $3}' | tr -d ,) compose=$(docker compose version --short)"
