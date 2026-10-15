#!/usr/bin/env bash
# 서버 안에서 비밀값을 생성한다(이미 있으면 덮어쓰지 않음). 값은 출력하지 않는다.
#   sudo setup-secrets.sh prod-data | dev
#   sudo setup-secrets.sh prod-app-env <DATA_PRIVATE_IP>   ← 표준입력으로 "PG_APP_PASSWORD REDIS_PASSWORD" 한 줄
#   sudo setup-secrets.sh dev-app-env                       ← 같은 VM의 개발 DB 비밀값으로 dev-be.env 작성
# APP_UID: 앱 컨테이너 실행 UID (ject-smoke=65532). 앱 이미지가 바뀌면 다시 맞춘다.
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
maxmemory-policy noeviction
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
*) echo "usage: setup-secrets.sh prod-data|dev|prod-app-env <ip>|dev-app-env" >&2; exit 2 ;;
esac
