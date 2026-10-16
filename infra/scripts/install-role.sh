#!/usr/bin/env bash
# infra/ 묶음을 VM에 설치한다(멱등). 관리자 PC에서 infra/를 /tmp/ject-infra로 복사한 뒤:
#   sudo bash /tmp/ject-infra/scripts/install-role.sh <prod-app|prod-data|dev>
# 이 스크립트는 서비스를 시작하지 않는다. 시작 절차는 infra/README.md의 순서를 따른다.
set -euo pipefail
ROLE="${1:?prod-app|prod-data|dev}"
GHCR_OWNER="${2:?GHCR 소유자(소문자) — 배포 허용 이미지를 ghcr.io/<owner>/ject- 로 제한}"
[[ "$GHCR_OWNER" =~ ^[a-z0-9-]+$ ]] || { echo "GHCR 소유자 형식 오류" >&2; exit 2; }
SRC="$(cd "$(dirname "$0")/.." && pwd)"
install -d -m 0755 /opt/ject/bin /opt/ject/compose /opt/ject/compose/initdb /etc/ject

install -m 0755 "$SRC/scripts/setup-secrets.sh" /opt/ject/bin/setup-secrets.sh
install -m 0755 "$SRC/scripts/ject-user" /opt/ject/bin/ject-user

# Nginx가 있는 서버(운영 앱, 개발)만. render-nginx.sh는 SRC_DIR/nginx/nginx.conf를 읽으므로 /opt/ject 아래에 같은 구조를 둔다.
install_nginx_tools() {
  install -d -m 0755 /opt/ject/nginx
  install -m 0755 "$SRC/scripts/render-nginx.sh" /opt/ject/bin/render-nginx.sh
  install -m 0644 "$SRC/nginx/nginx.conf" /opt/ject/nginx/nginx.conf
}

case "$ROLE" in
prod-app)
  install_nginx_tools
  install -m 0755 "$SRC/scripts/ject-deploy" "$SRC/scripts/ject-deploy-gate" "$SRC/scripts/ject-deploy-key" /opt/ject/bin/
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
  install -m 0755 "$SRC/scripts/ject-backup-metrics" /opt/ject/bin/
  install -m 0644 "$SRC/systemd/ject-pg-backup."{service,timer} "$SRC/systemd/ject-pg-restore-test."{service,timer} "$SRC/systemd/ject-backup-metrics.service" /etc/systemd/system/
  if [ ! -x /opt/ject/oci-cli/bin/oci ]; then
    python3 -m venv /opt/ject/oci-cli
    /opt/ject/oci-cli/bin/pip install -q --upgrade pip oci-cli
  fi
  [ -f /etc/ject/backup.conf ] || printf 'BUCKET=ject-db-backups\nPREFIX=postgres/prod\nRETAIN=7\n' > /etc/ject/backup.conf
  systemctl daemon-reload
  systemctl enable --now ject-pg-backup.timer ject-pg-restore-test.timer >/dev/null
  systemctl enable ject-backup-metrics.service >/dev/null
  systemctl start ject-backup-metrics.service ;;
dev)
  install_nginx_tools
  install -m 0755 "$SRC/scripts/ject-deploy" "$SRC/scripts/ject-deploy-gate" "$SRC/scripts/ject-deploy-key" /opt/ject/bin/
  install -m 0644 "$SRC/compose/dev-data.yaml" "$SRC/compose/dev-app.yaml" "$SRC/compose/dev-gateway.yaml" /opt/ject/compose/
  install -m 0755 "$SRC/compose/initdb/10-app-role.sh" /opt/ject/compose/initdb/
  docker network inspect ject-dev-net >/dev/null 2>&1 || docker network create ject-dev-net >/dev/null
  install -d /srv/ject/dev/nginx/conf.d
  # 개발 게이트웨이는 VM 사설 IP에만 바인딩한다(ject-deploy와 compose가 같은 값을 읽음).
  [ -f /etc/ject/host.env ] || echo "DEV_BIND_IP=$(hostname -I | awk '{print $1}')" > /etc/ject/host.env
  # 관측 스택(ject-obs): Prometheus·Loki·Grafana·obs-gateway 설정과 데이터 디렉터리
  O="$SRC/observability"
  install -m 0644 "$SRC/compose/obs.yaml" /opt/ject/compose/
  install -d -m 0755 /etc/ject/prometheus /etc/ject/loki /etc/ject/obs-gateway/conf.d /etc/ject/grafana
  install -m 0644 "$O/prometheus/prometheus.yml" /etc/ject/prometheus/prometheus.yml
  install -m 0644 "$O/loki/loki.yaml" /etc/ject/loki/loki.yaml
  install -m 0644 "$SRC/nginx/nginx.conf" /etc/ject/obs-gateway/nginx.conf
  install -m 0644 "$O/gateway/obs-gateway.conf" /etc/ject/obs-gateway/conf.d/obs-gateway.conf
  rm -rf /etc/ject/grafana/provisioning /etc/ject/grafana/dashboards
  cp -R "$O/grafana/provisioning" "$O/grafana/dashboards" /etc/ject/grafana/
  chmod -R a+rX /etc/ject/grafana
  install -d -m 0750 -o 65534 -g 65534 /srv/ject/observability/prometheus
  install -d -m 0750 -o 10001 -g 10001 /srv/ject/observability/loki
  install -d -m 0750 -o 472 -g 472 /srv/ject/observability/grafana
  # 알림 중계(호스트 systemd, 127.0.0.1:9095): oci SDK가 든 가상환경을 쓴다
  if [ ! -x /opt/ject/oci-cli/bin/oci ]; then
    python3 -m venv /opt/ject/oci-cli
    /opt/ject/oci-cli/bin/pip install -q --upgrade pip oci-cli
  fi
  install -m 0755 "$O/relay/ject-alert-relay" /opt/ject/bin/ject-alert-relay
  install -m 0644 "$SRC/systemd/ject-alert-relay.service" /etc/systemd/system/
  [ -f /etc/ject/alert-relay.env ] || printf 'ALERT_TOPIC_ID=\nRELAY_LISTEN=127.0.0.1:9095\n' > /etc/ject/alert-relay.env
  systemctl daemon-reload ;;
*) echo "unknown role" >&2; exit 2 ;;
esac

# ---- 공통: 수집기(ject-agent = Node Exporter + Alloy) ------------------------------
# 역할별 Alloy 설정: 공통 + 앱 지표(prod-app, dev) + 관측 도구·공인 주소 시험(dev)
install -m 0644 "$SRC/compose/agent.yaml" /opt/ject/compose/
install -d -m 0755 /etc/ject/alloy /var/lib/ject/textfile
install -d -m 0700 /srv/ject/observability/alloy
rm -f /etc/ject/alloy/*.alloy
install -m 0644 "$SRC/observability/alloy/common.alloy" /etc/ject/alloy/
case "$ROLE" in prod-app|dev) install -m 0644 "$SRC/observability/alloy/app.alloy" /etc/ject/alloy/ ;; esac
[ "$ROLE" = dev ] && install -m 0644 "$SRC/observability/alloy/obs.alloy" /etc/ject/alloy/
# /etc/ject/obs.env: 수집기 환경(호스트 이름·환경·보낼 주소). 이미 있으면 유지한다(setup-secrets.sh obs-env가 만든다).
true

# 배포 허용 이미지: ghcr.io/<owner>/ject- 로 시작하는 것만
[ -f /etc/ject/deploy.conf ] || printf 'ALLOWED_IMAGE_PREFIX=ghcr.io/%s/ject-\nMIN_FREE_PCT=15\nWAIT_TIMEOUT=180\nKEEP_IMAGES=3\n' "$GHCR_OWNER" > /etc/ject/deploy.conf
echo "installed role=$ROLE"
