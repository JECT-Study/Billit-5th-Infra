#!/usr/bin/env bash
# 비밀값은 서버 안에서 만든다. 이미 있으면 그대로 두고, 값은 화면에 찍지 않는다.
#   sudo setup-secrets.sh prod-data | dev                   DB/Redis 비밀번호
#   sudo setup-secrets.sh prod-app-env <DATA_PRIVATE_IP>    stdin 한 줄: "PG_APP_PASSWORD REDIS_PASSWORD"
#   sudo setup-secrets.sh dev-app-env                       같은 VM의 개발 DB 값으로 dev-be.env
#   sudo setup-secrets.sh obs                               (dev) Grafana 관리자, 수집기 쓰기 비밀번호, obs-gateway 해시
#   sudo setup-secrets.sh obs-push                          (prod) stdin 한 줄 = dev VM의 obs_push_password
#   sudo setup-secrets.sh obs-env <host> <env> <DEV_IP>     /etc/ject/obs.env
#   sudo setup-secrets.sh dev-swagger                       (dev) Swagger Basic 인증(사용자 ject)
# APP_UID: 앱 컨테이너 UID(ject-smoke=65532). 앱 이미지가 바뀌면 맞춘다.
set -euo pipefail
umask 077
S=/srv/ject/secrets
install -d -m 0700 "$S"
APP_UID="${APP_UID:-65532}"
gen() { head -c 48 /dev/urandom | base64 | tr -dc 'A-Za-z0-9' | cut -c1-40; }
mk() {   # file owner(uid) [value]
  local f="$S/$1"
  if [ ! -s "$f" ]; then printf '%s' "${3:-$(gen)}" > "$f"; echo "created $1"; else echo "kept $1"; fi
  chown "$2:$2" "$f"; chmod 0400 "$f"
}
redis_conf() {   # maxmemory
  local f="$S/redis.conf"
  if [ ! -s "$f" ]; then
    cat > "$f" <<EOF
bind 0.0.0.0
protected-mode yes
port 6379
requirepass $(cat "$S/redis_password")
appendonly yes
appendfsync everysec
maxmemory $1
maxmemory-policy allkeys-lru
dir /data
EOF
    echo "created redis.conf"
  else echo "kept redis.conf"; fi
  chown 999:999 "$f"; chmod 0400 "$f"
}

case "${1:-}" in
prod-data|dev)
  mk pg_admin_password 999
  mk pg_app_password 999
  mk redis_password 999
  [ "$1" = prod-data ] && redis_conf 384mb || redis_conf 96mb
  if [ "$1" = dev ]; then
    mk app_redis_password "$APP_UID" "$(cat "$S/redis_password")"
  fi ;;
prod-app-env)
  DATA_IP="${2:?DATA_PRIVATE_IP}"
  read -r PG_APP_PW REDIS_PW || true
  [ -n "${PG_APP_PW:-}" ] && [ -n "${REDIS_PW:-}" ] || { echo "stdin 값 없음" >&2; exit 1; }
  printf '%s' "$REDIS_PW" > "$S/app_redis_password.new"
  chown "$APP_UID:$APP_UID" "$S/app_redis_password.new"; chmod 0400 "$S/app_redis_password.new"
  mv "$S/app_redis_password.new" "$S/app_redis_password"; echo "wrote app_redis_password"
  cat > "$S/prod-be.env" <<EOF
DB_HOST=$DATA_IP
DB_PORT=5432
DB_NAME=ject
DB_USER=ject_app
DB_PASSWORD=$PG_APP_PW
SPRING_DATASOURCE_URL=jdbc:postgresql://$DATA_IP:5432/ject
SPRING_DATASOURCE_USERNAME=ject_app
SPRING_DATASOURCE_PASSWORD=$PG_APP_PW
REDIS_HOST=$DATA_IP
REDIS_PORT=6379
REDIS_PASSWORD_FILE=/run/secrets/redis_password
EOF
  chmod 0400 "$S/prod-be.env"; echo "wrote prod-be.env" ;;
dev-app-env)
  PG_APP_PW="$(cat "$S/pg_app_password")"
  cat > "$S/dev-be.env" <<EOF
DB_HOST=postgres
DB_PORT=5432
DB_NAME=ject_dev
DB_USER=ject_dev_app
DB_PASSWORD=$PG_APP_PW
SPRING_DATASOURCE_URL=jdbc:postgresql://postgres:5432/ject_dev
SPRING_DATASOURCE_USERNAME=ject_dev_app
SPRING_DATASOURCE_PASSWORD=$PG_APP_PW
REDIS_HOST=redis
REDIS_PORT=6379
REDIS_PASSWORD_FILE=/run/secrets/redis_password
EOF
  chmod 0400 "$S/dev-be.env"; echo "wrote dev-be.env" ;;
obs)
  mk grafana_admin_password 472
  mk obs_push_password 0
  install -d -m 0755 /etc/ject/obs-gateway/conf.d
  # nginx 워커(UID 101)가 읽는다. SHA-512 crypt(musl crypt 지원)
  printf 'ject-agent:%s\n' "$(openssl passwd -6 -stdin < "$S/obs_push_password")" > /etc/ject/obs-gateway/conf.d/obs.htpasswd.new
  chown 0:101 /etc/ject/obs-gateway/conf.d/obs.htpasswd.new; chmod 0440 /etc/ject/obs-gateway/conf.d/obs.htpasswd.new
  mv /etc/ject/obs-gateway/conf.d/obs.htpasswd.new /etc/ject/obs-gateway/conf.d/obs.htpasswd; echo "wrote obs.htpasswd" ;;
obs-push)
  read -r PUSH_PW || true
  [ -n "${PUSH_PW:-}" ] || { echo "stdin 값 없음" >&2; exit 1; }
  printf '%s' "$PUSH_PW" > "$S/obs_push_password.new"; chmod 0400 "$S/obs_push_password.new"
  mv "$S/obs_push_password.new" "$S/obs_push_password"; echo "wrote obs_push_password" ;;
obs-env)
  H="${2:?host}"; E="${3:?env}"; DIP="${4:?DEV_PRIVATE_IP}"
  if [ "$H" = dev ]; then P=127.0.0.1; else P="$DIP"; fi
  umask 022
  cat > /etc/ject/obs.env <<EOF
JECT_HOST=$H
JECT_ENV=$E
OBS_PROM_URL=http://$P:9090/api/v1/write
OBS_LOKI_URL=http://$P:3100/loki/api/v1/push
OBS_PUSH_USER=ject-agent
PROBE_PROD_URL=${PROBE_PROD_URL:-}
PROBE_DEV_URL=${PROBE_DEV_URL:-}
EOF
  echo "wrote /etc/ject/obs.env" ;;
dev-swagger)
  mk dev_swagger_password 0
  install -d -m 0755 /srv/ject/dev/nginx/conf.d
  printf 'ject:%s\n' "$(openssl passwd -6 -stdin < "$S/dev_swagger_password")" > /srv/ject/dev/nginx/conf.d/swagger.htpasswd.new
  chown 0:101 /srv/ject/dev/nginx/conf.d/swagger.htpasswd.new; chmod 0440 /srv/ject/dev/nginx/conf.d/swagger.htpasswd.new
  mv /srv/ject/dev/nginx/conf.d/swagger.htpasswd.new /srv/ject/dev/nginx/conf.d/swagger.htpasswd
  echo "wrote swagger.htpasswd (사용자 ject, 비밀번호: sudo cat $S/dev_swagger_password)" ;;
*) echo "usage: setup-secrets.sh prod-data|dev|prod-app-env <ip>|dev-app-env|obs|obs-push|obs-env <host> <env> <dev-ip>|dev-swagger" >&2; exit 2 ;;
esac
