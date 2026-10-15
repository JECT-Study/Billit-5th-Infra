#!/usr/bin/env bash
# infra/ 묶음을 VM에 설치한다(멱등). 관리자 PC에서 infra/를 /tmp/ject-infra로 복사한 뒤:
#   sudo bash /tmp/ject-infra/scripts/install-role.sh <prod-app|prod-data|dev>
# 이 스크립트는 서비스를 시작하지 않는다. 시작 절차는 infra/README.md의 순서를 따른다.
set -euo pipefail
ROLE="${1:?prod-app|prod-data|dev}"
GHCR_OWNER="${2:?GHCR 소유자(소문자) — 배포 허용 이미지를 ghcr.io/<owner>/ject- 로 제한}"
[[ "$GHCR_OWNER" =~ ^[a-z0-9-]+$ ]] || { echo "GHCR 소유자 형식 오류" >&2; exit 2; }
SRC="$(cd "$(dirname "$0")/.." && pwd)"
install -d -m 0755 /opt/ject/bin /opt/ject/compose /opt/ject/compose/initdb /opt/ject/nginx /etc/ject

install -m 0755 "$SRC/scripts/render-nginx.sh" /opt/ject/bin/render-nginx.sh
install -m 0755 "$SRC/scripts/setup-secrets.sh" /opt/ject/bin/setup-secrets.sh
install -m 0755 "$SRC/scripts/ject-user" /opt/ject/bin/ject-user
install -m 0644 "$SRC/nginx/nginx.conf" /opt/ject/nginx/nginx.conf
# render-nginx.sh는 SRC_DIR/nginx/nginx.conf를 읽으므로 /opt/ject 아래에 같은 구조를 둔다.

case "$ROLE" in
prod-app)
  install -m 0755 "$SRC/scripts/ject-deploy" /opt/ject/bin/ject-deploy
  install -m 0755 "$SRC/scripts/ject-cert" /opt/ject/bin/ject-cert
  install -m 0644 "$SRC/compose/prod-edge.yaml" "$SRC/compose/prod-app.yaml" /opt/ject/compose/
  install -m 0644 "$SRC/systemd/ject-certbot-renew.service" "$SRC/systemd/ject-certbot-renew.timer" /etc/systemd/system/
  docker network inspect ject-prod-net >/dev/null 2>&1 || docker network create ject-prod-net >/dev/null
  install -d /srv/ject/app/nginx/conf.d
  [ -f /srv/ject/app/edge.env ] || printf 'PROD_DOMAIN=\nDEV_DOMAIN=\nDEV_UPSTREAM=\nCERT_NAME=ject\nACME_EMAIL=\n' > /srv/ject/app/edge.env
  systemctl daemon-reload
  systemctl enable --now ject-certbot-renew.timer >/dev/null ;;
prod-data)
  install -m 0755 "$SRC/scripts/ject-pg-backup" "$SRC/scripts/ject-pg-restore-test" /opt/ject/bin/
  install -m 0644 "$SRC/compose/prod-data.yaml" /opt/ject/compose/
  install -m 0755 "$SRC/compose/initdb/10-app-role.sh" /opt/ject/compose/initdb/
  install -m 0644 "$SRC/systemd/ject-pg-backup."{service,timer} "$SRC/systemd/ject-pg-restore-test."{service,timer} /etc/systemd/system/
  if [ ! -x /opt/ject/oci-cli/bin/oci ]; then
    python3 -m venv /opt/ject/oci-cli
    /opt/ject/oci-cli/bin/pip install -q --upgrade pip oci-cli
  fi
  [ -f /etc/ject/backup.conf ] || printf 'BUCKET=ject-db-backups\nPREFIX=postgres/prod\nRETAIN=7\n' > /etc/ject/backup.conf
  systemctl daemon-reload
  systemctl enable --now ject-pg-backup.timer ject-pg-restore-test.timer >/dev/null ;;
dev)
  install -m 0755 "$SRC/scripts/ject-deploy" /opt/ject/bin/ject-deploy
  install -m 0644 "$SRC/compose/dev-data.yaml" "$SRC/compose/dev-app.yaml" "$SRC/compose/dev-gateway.yaml" /opt/ject/compose/
  install -m 0755 "$SRC/compose/initdb/10-app-role.sh" /opt/ject/compose/initdb/
  docker network inspect ject-dev-net >/dev/null 2>&1 || docker network create ject-dev-net >/dev/null
  install -d /srv/ject/dev/nginx/conf.d
  # 개발 게이트웨이는 VM 사설 IP에만 바인딩한다(ject-deploy와 compose가 같은 값을 읽음).
  [ -f /etc/ject/host.env ] || echo "DEV_BIND_IP=$(hostname -I | awk '{print $1}')" > /etc/ject/host.env ;;
*) echo "unknown role" >&2; exit 2 ;;
esac

# 배포 허용 이미지: ghcr.io/<owner>/ject- 로 시작하는 것만
[ -f /etc/ject/deploy.conf ] || printf 'ALLOWED_IMAGE_PREFIX=ghcr.io/%s/ject-\nMIN_FREE_PCT=15\nWAIT_TIMEOUT=180\nKEEP_IMAGES=3\n' "$GHCR_OWNER" > /etc/ject/deploy.conf
echo "installed role=$ROLE"
