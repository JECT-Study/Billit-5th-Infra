#!/usr/bin/env bash
# 격리 VM 전용: 운영/개인 Docker context, bind mount, published port 사용 금지.
set -euo pipefail
D=(docker --context colima-billit-verify)
ROOT=$(cd "$(dirname "$0")/.." && pwd)
TMP=$(mktemp -d)
NAME="billit-redis-test-$$"
REDIS="$NAME-redis"
ALLOY="$NAME-alloy"
cleanup() {
  "${D[@]}" rm -fv "$ALLOY" "$REDIS" >/dev/null 2>&1 || true
  rm -rf "$TMP"
}
trap cleanup EXIT
umask 077
"${D[@]}" info --format 'Docker {{.ServerVersion}} / {{.Architecture}}'
for img in redis:7.4.11-bookworm grafana/alloy:v1.20.1; do
  "${D[@]}" image inspect "$img" --format '{{index .RepoDigests 0}}'
done
# 비밀은 전부 이 시험만의 합성값이며 실제 서비스 자격증명이 아니다.
cat > "$TMP/redis.conf" <<'CONF'
bind 127.0.0.1
protected-mode yes
save ""
appendonly no
maxmemory 8mb
maxmemory-policy allkeys-lru
user default on nopass ~* &* +@all
user metrics on >synthetic-metrics-only -@all +ping +info +config|get +slowlog|get +slowlog|len +latency|latest +latency|histogram
CONF
chmod 644 "$TMP/redis.conf"
printf '%s\n' synthetic-metrics-only > "$TMP/redis_metrics_password"
cp "$ROOT/observability/alloy/redis.alloy.example" "$TMP/config.alloy"
cat >> "$TMP/config.alloy" <<'CONF'

// 격리 시험용 sink. 외부 remote write/알림은 발생하지 않는다.
prometheus.relabel "host" {
  forward_to = []
}
CONF
"${D[@]}" create --name "$REDIS" --network none --tmpfs /data redis:7.4.11-bookworm redis-server /tmp/redis.conf >/dev/null
"${D[@]}" cp "$TMP/redis.conf" "$REDIS:/tmp/redis.conf"
"${D[@]}" start "$REDIS" >/dev/null
# shellcheck disable=SC2016 # 컨테이너 내부에서 변수 확장
"${D[@]}" exec "$REDIS" sh -c 'df -Pm / | tail -1; test "$(df -Pm / | awk "NR==2 {print \$4}")" -gt 512'
"${D[@]}" create --name "$ALLOY" --network "container:$REDIS" \
  -e JECT_REDIS_METRICS_ADDR=redis://127.0.0.1:6379 -e JECT_REDIS_METRICS_USER=metrics \
  grafana/alloy:v1.20.1 run --disable-reporting --server.http.listen-addr=127.0.0.1:12345 /etc/alloy/config.alloy >/dev/null
"${D[@]}" cp "$TMP/config.alloy" "$ALLOY:/etc/alloy/config.alloy"
# docker cp로 secret 디렉터리를 생성. 호스트 홈/비밀/볼륨을 마운트하지 않는다.
mkdir "$TMP/secrets"
cp "$TMP/redis_metrics_password" "$TMP/secrets/"
"${D[@]}" cp "$TMP/secrets" "$ALLOY:/run/secrets"
"${D[@]}" start "$ALLOY" >/dev/null
"${D[@]}" exec "$ALLOY" /bin/alloy validate /etc/alloy/config.alloy
metric() {
  "${D[@]}" exec "$ALLOY" bash -c 'exec 3<>/dev/tcp/127.0.0.1/12345; printf "GET /api/v0/component/prometheus.exporter.redis.ject/metrics HTTP/1.0\r\nHost: localhost\r\n\r\n" >&3; cat <&3' > "$TMP/metrics"
}
wait_metric() {
  local expected=$1
  for ((i=0;i<20;i++)); do
    if metric 2>/dev/null && grep -Eq "$expected" "$TMP/metrics"; then return; fi
    sleep 0.25
  done
  cat "$TMP/metrics"
  "${D[@]}" logs "$ALLOY" --tail 15
  return 1
}
wait_metric '^redis_up 1'
grep -q '^redis_exporter_last_scrape_error{err=""} 0' "$TMP/metrics"
[[ -z $("${D[@]}" exec "$REDIS" redis-cli --raw ACL LOG) ]]
printf 'PASS exporter scrape error=0 and no ACL denials\n'
grep -E '^redis_(memory_used_bytes|memory_max_bytes|evicted_keys_total|up) ' "$TMP/metrics"
grep -q '^redis_memory_max_bytes 8.388608e+06' "$TMP/metrics"
grep -q '^redis_evicted_keys_total 0' "$TMP/metrics"
# 값/키 읽기 및 실행 권한이 없음을 직접 확인한다.
for command in 'GET synthetic-key' 'SET synthetic-key value' 'EVAL return 0' 'KEYS *' 'CONFIG SET maxmemory 0'; do
  # shellcheck disable=SC2016 # 고정 합성 명령을 컨테이너 내부에서 확장
  result=$("${D[@]}" exec -e REDISCLI_AUTH=synthetic-metrics-only "$REDIS" sh -c 'redis-cli --user metrics $1' sh "$command")
  [[ "$result" == *NOPERM* ]]
done
printf 'PASS restricted ACL denies key reads/writes, EVAL, KEYS, CONFIG SET\n'
# 인증 실패를 정상0값/연결 성공으로 오인하지 않는다. ACL 비활성화→복구.
"${D[@]}" exec "$REDIS" redis-cli ACL SETUSER metrics off >/dev/null
"${D[@]}" exec "$REDIS" redis-cli CLIENT KILL USER metrics >/dev/null
wait_metric '^redis_up 0'
printf 'PASS authentication failure redis_up=0\n'
"${D[@]}" exec "$REDIS" redis-cli ACL SETUSER metrics on >/dev/null
wait_metric '^redis_up 1'
printf 'PASS authentication recovery redis_up=1\n'
# 한 개 합성키만 생성한 뒤 격리 Redis 한도 축소로 축출 계수 변화를 검사한다.
"${D[@]}" exec "$REDIS" redis-cli SET synthetic-key synthetic-value >/dev/null
"${D[@]}" exec "$REDIS" redis-cli CONFIG SET maxmemory 1 >/dev/null
wait_metric '^redis_evicted_keys_total 1'
printf 'PASS single synthetic key eviction counter=1\n'
# 무제한 메모리 경계도 0으로 노출되는지 확인한다(합성 인스턴스만).
"${D[@]}" exec "$REDIS" redis-cli CONFIG SET maxmemory 0 >/dev/null
wait_metric '^redis_memory_max_bytes 0'
printf 'PASS unlimited-memory boundary maxmemory=0\n'
if grep -Eq 'synthetic-key|synthetic-metrics-only' "$TMP/metrics"; then exit 1; fi

printf 'PASS exporter validation/ACL/authentication/memory/eviction-metric presence; no alert delivery or production workload tested\n'
