#!/usr/bin/env bash
# 로컬 모니터링 시험 (Ubuntu 24.04 ARM64 + Docker, root). 한 호스트에 개발·모니터링 VM 역할(ject-obs)을 설치하고,
# 수집기(ject-agent)는 운영 VM처럼 obs-gateway(Basic 인증)로 밀어 넣게 해서 전체 경로를 확인한다.
# 알림 중계는 DRY_RUN=1(OCI로 보내지 않고 로그만)로 띄운다. 실제 OCI 발행은 서버에서 따로 확인한다.
#   sudo bash infra/tests/local-obs-e2e.sh
set -euo pipefail
INFRA="$(cd "$(dirname "$0")/.." && pwd)"
PASS=0; FAIL=0
ok()   { echo "PASS: $*"; PASS=$((PASS+1)); }
bad()  { echo "FAIL: $*"; FAIL=$((FAIL+1)); }
check() { local d="$1"; shift; if "$@" >/dev/null 2>&1; then ok "$d"; else bad "$d"; fi; }
retry() { local n="$1"; shift; for _ in $(seq 1 "$n"); do if "$@" >/dev/null 2>&1; then return 0; fi; sleep 5; done; return 1; }
HOST_IP="$(hostname -I | awk '{print $1}')"
exec > >(tee /var/log/ject-obs-e2e.log) 2>&1
export COMPOSE_PROGRESS=quiet

echo "== 준비 (이 시험 호스트 전용 상태 초기화) =="
for pr in ject-obs ject-agent ject-test ject-dev-gateway ject-dev-data; do docker compose -p "$pr" down -v --remove-orphans >/dev/null 2>&1 || true; done
systemctl stop ject-alert-relay 2>/dev/null || true
rm -rf /srv/ject /etc/ject /opt/ject /var/lib/ject
mkdir -p /etc/ject /srv/ject/secrets
getent group ject-admins >/dev/null || groupadd ject-admins
# 가상환경 설치(pip oci-cli)는 시험에서 건너뛴다: 시스템 python3로 DRY_RUN 중계를 띄운다.
mkdir -p /opt/ject/oci-cli/bin && ln -sf "$(command -v python3)" /opt/ject/oci-cli/bin/python3 && ln -sf /bin/true /opt/ject/oci-cli/bin/oci
bash "$INFRA/scripts/install-role.sh" dev e2e
bash "$INFRA/scripts/install-role.sh" prod-data e2e
systemctl disable --now ject-pg-backup.timer ject-pg-restore-test.timer >/dev/null 2>&1 || true
. /etc/ject/host.env

echo "== C3 Redis 캐시 정책 =="
bash /opt/ject/bin/setup-secrets.sh dev >/dev/null
check "redis.conf allkeys-lru" grep -qx 'maxmemory-policy allkeys-lru' /srv/ject/secrets/redis.conf
docker network inspect ject-dev-net >/dev/null 2>&1 || docker network create ject-dev-net >/dev/null
docker compose -p ject-dev-data -f /opt/ject/compose/dev-data.yaml up -d --wait redis >/dev/null
check "실행 중 Redis 정책 allkeys-lru" bash -c "REDISCLI_AUTH=\"\$(cat /srv/ject/secrets/redis_password)\" docker exec -e REDISCLI_AUTH ject-dev-data-redis-1 redis-cli config get maxmemory-policy | grep -qx allkeys-lru"
check "AOF 유지" bash -c "REDISCLI_AUTH=\"\$(cat /srv/ject/secrets/redis_password)\" docker exec -e REDISCLI_AUTH ject-dev-data-redis-1 redis-cli config get appendonly | grep -qx yes"

echo "== C2 개발 게이트웨이 Swagger (Basic 인증) =="
docker rm -f e2e-be >/dev/null 2>&1 || true
docker run -d --name e2e-be --network ject-dev-net --network-alias be nginx:1.30.6-alpine sh -c \
  'printf "server{listen 8080; location / {return 200 \"be:\$uri auth=[\$http_authorization] proto=\$http_x_forwarded_proto\";}}" > /etc/nginx/conf.d/default.conf && nginx -g "daemon off;"' >/dev/null
install -d /srv/ject/dev/nginx/conf.d
bash /opt/ject/bin/render-nginx.sh dev-gateway >/dev/null
docker compose -p ject-dev-gateway -f /opt/ject/compose/dev-gateway.yaml --env-file /etc/ject/host.env up -d --wait >/dev/null
GW="http://$DEV_BIND_IP:8080"
check "비밀번호 파일 전: /swagger-ui 404" bash -c "[ \$(curl -s -o /dev/null -w '%{http_code}' $GW/swagger-ui/index.html) = 404 ]"
bash /opt/ject/bin/setup-secrets.sh dev-swagger >/dev/null
bash /opt/ject/bin/render-nginx.sh dev-gateway >/dev/null
docker exec ject-dev-gateway-nginx-1 nginx -s reload; sleep 1
SW="$(cat /srv/ject/secrets/dev_swagger_password)"
check "인증 없이 /swagger-ui 401" bash -c "[ \$(curl -s -o /dev/null -w '%{http_code}' $GW/swagger-ui/index.html) = 401 ]"
check "틀린 비밀번호 401" bash -c "[ \$(curl -s -o /dev/null -w '%{http_code}' -u ject:wrong $GW/v3/api-docs) = 401 ]"
check "인증 후 /v3/api-docs 200(앱으로 전달)" bash -c "curl -fsS -u 'ject:$SW' $GW/v3/api-docs | grep -q 'be:/v3/api-docs'"
check "앱에 Authorization 헤더 전달 안 함" bash -c "curl -fsS -u 'ject:$SW' $GW/swagger-ui/index.html | grep -q 'auth=\[\]'"
check "개발 게이트웨이: 앞단 X-Forwarded-Proto(https) 유지" bash -c "curl -fsS -H 'X-Forwarded-Proto: https' $GW/api/x | grep -q 'proto=https'"
check "개발 게이트웨이: 앞단 값 없으면 자기 scheme" bash -c "curl -fsS $GW/api/x | grep -q 'proto=http\$'"
check "개발 /actuator 계속 404" bash -c "[ \$(curl -s -o /dev/null -w '%{http_code}' -u 'ject:$SW' $GW/actuator/health) = 404 ]"
check "개발 /api 인증 없이 통과" bash -c "curl -fsS $GW/api/x | grep -q 'be:/api/x'"
check "운영 규칙은 Swagger 404 유지(edge 템플릿)" grep -q 'swagger-ui|v3/api-docs) { return 404; }' /opt/ject/bin/render-nginx.sh

echo "== 관측 스택 (ject-obs) =="
bash /opt/ject/bin/setup-secrets.sh obs >/dev/null
docker compose -p ject-obs -f /opt/ject/compose/obs.yaml --env-file /etc/ject/host.env up -d >/dev/null
check "Prometheus 준비" retry 24 curl -fsS http://127.0.0.1:9090/-/ready
check "Loki 준비" retry 36 curl -fsS http://127.0.0.1:3100/ready
check "Grafana 준비" retry 36 curl -fsS http://127.0.0.1:3000/api/health
check "Prometheus 보존 14d" bash -c "curl -fsS http://127.0.0.1:9090/api/v1/status/flags | grep -q '\"storage.tsdb.retention.time\":\"2w\"'"
check "Loki 보존 168h·compactor 삭제" bash -c "curl -fsS http://127.0.0.1:3100/config | grep -q 'retention_period: 1w' && curl -fsS http://127.0.0.1:3100/config | grep -q 'retention_enabled: true'"
PUSH="$(cat /srv/ject/secrets/obs_push_password)"
check "게이트웨이: 인증 없는 쓰기 401" bash -c "[ \$(curl -s -o /dev/null -w '%{http_code}' -X POST http://$DEV_BIND_IP:9090/api/v1/write) = 401 ]"
check "게이트웨이: 조회 API 차단 404" bash -c "[ \$(curl -s -o /dev/null -w '%{http_code}' -u 'ject-agent:$PUSH' http://$DEV_BIND_IP:9090/api/v1/query?query=up) = 404 ]"
check "게이트웨이: Loki 조회 차단 404" bash -c "[ \$(curl -s -o /dev/null -w '%{http_code}' -u 'ject-agent:$PUSH' http://$DEV_BIND_IP:3100/loki/api/v1/labels) = 404 ]"
check "게이트웨이: 인증 후 Loki push 204" bash -c "[ \$(curl -s -o /dev/null -w '%{http_code}' -u 'ject-agent:$PUSH' -H 'Content-Type: application/json' -X POST http://$DEV_BIND_IP:3100/loki/api/v1/push --data '{\"streams\":[{\"stream\":{\"job\":\"e2e\"},\"values\":[[\"'\$(date +%s%N)'\",\"hello\"]]}]}') = 204 ]"
check "Prometheus·Loki는 사설 IP 직접 접근 불가(게이트웨이만)" bash -c "! curl -fsS -m 3 http://$DEV_BIND_IP:9090/-/ready"

echo "== 알림 중계 (DRY_RUN) =="
printf 'ALERT_TOPIC_ID=\nRELAY_LISTEN=127.0.0.1:9095\nDRY_RUN=1\n' > /etc/ject/alert-relay.env
systemctl daemon-reload; systemctl restart ject-alert-relay
check "중계기 /healthz" retry 6 curl -fsS http://127.0.0.1:9095/healthz
check "중계기 /test" bash -c "curl -fsS -X POST http://127.0.0.1:9095/test | grep -q sent"
check "중계기 외부 주소에서 안 들림" bash -c "! curl -fsS -m 3 http://$DEV_BIND_IP:9095/healthz"

echo "== 수집기 (ject-agent, 운영 VM처럼 게이트웨이 경유) =="
bash /opt/ject/bin/setup-secrets.sh obs-env prod-data prod "$DEV_BIND_IP" >/dev/null
check "obs.env 게이트웨이 주소" grep -q "OBS_PROM_URL=http://$DEV_BIND_IP:9090/api/v1/write" /etc/ject/obs.env
# 백업 지표(textfile): 실패 → 알림 조건, 그 뒤 성공으로 되돌림
install -d /srv/ject/backup-status
echo '{"run_id":"x","result":"failed","stage":"upload","duration_s":3,"bytes":0,"time":"'"$(date -Iseconds)"'"}' > /srv/ject/backup-status/last.json
echo '{"run_id":"y","result":"success","stage":"complete","duration_s":20,"bytes":12345,"time":"'"$(date -Iseconds -d '-1 hour')"'"}' > /srv/ject/backup-status/last-success.json
systemctl start ject-backup-metrics
check "textfile 지표 생성" grep -q '^ject_backup_last_run_success 0' /var/lib/ject/textfile/ject_backup.prom
docker compose -p ject-agent -f /opt/ject/compose/agent.yaml --env-file /etc/ject/obs.env up -d >/dev/null
# 민감정보가 섞인 로그를 내는 시험 컨테이너(ject- 프로젝트)
cat > /tmp/ject-test.yaml <<'EOF'
name: ject-test
services:
  leaky:
    image: busybox:stable
    command: ["sh", "-c", "while true; do echo '{\"level\":\"ERROR\",\"message\":\"login user=kim@example.com phone=010-1234-5678 Authorization: Bearer abc.def-123 password=hunter2 card 1234-5678-9012-3456 jwt eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U\"}'; echo 'receipt_raw {\"analyzeResult\": \"STARBUCKS 4500\"}'; echo '{\"level\":\"INFO\",\"message\":\"정상 로그 marker-ok\"}'; sleep 5; done"]
EOF
docker compose -f /tmp/ject-test.yaml up -d >/dev/null
q() { curl -fsS -G http://127.0.0.1:9090/api/v1/query --data-urlencode "query=$1"; }
check "node 지표 도착(host=prod-data)" retry 24 bash -c "q() { curl -fsS -G http://127.0.0.1:9090/api/v1/query --data-urlencode \"query=\$1\"; }; q 'up{job=\"node\",host=\"prod-data\"} == 1' | grep -q '\"value\"'"
check "백업 지표 도착" retry 12 bash -c "curl -fsS -G http://127.0.0.1:9090/api/v1/query --data-urlencode 'query=ject_backup_last_run_success{host=\"prod-data\"}' | grep -q '\"0\"'"
check "Alloy 자체 지표 도착" retry 12 bash -c "curl -fsS -G http://127.0.0.1:9090/api/v1/query --data-urlencode 'query=up{job=\"integrations/self\"}' | grep -q '\"value\"'"
lq() { curl -fsS -G http://127.0.0.1:3100/loki/api/v1/query_range --data-urlencode "query=$1" --data-urlencode "since=10m" --data-urlencode "limit=50"; }
check "로그 도착(project=ject-test)" retry 24 bash -c "curl -fsS -G http://127.0.0.1:3100/loki/api/v1/query_range --data-urlencode 'query={project=\"ject-test\"}' --data-urlencode since=10m | grep -q marker-ok"
L="$(lq '{project="ject-test"}' || true)"
for s in kim@example.com 010-1234-5678 abc.def-123 hunter2 1234-5678-9012-3456 dozjgNryP4J3jVmNHl0w5N STARBUCKS; do
  check "로그에 원문 없음: $s" bash -c "! printf '%s' \"\$1\" | grep -qF -- \"$s\"" _ "$L"
done
check "가림 표시 남음([REDACTED_EMAIL])" bash -c "printf '%s' \"\$1\" | grep -qF REDACTED_EMAIL" _ "$L"
check "라벨 없는 줄 없음(수집기 자신의 로그 제외)" bash -c "! curl -fsS -G http://127.0.0.1:3100/loki/api/v1/query_range --data-urlencode 'query={host=\"prod-data\", job=\"\"}' --data-urlencode since=2m | grep -q '\"values\"'"
check "level 라벨(error)" retry 6 bash -c "curl -fsS -G http://127.0.0.1:3100/loki/api/v1/query_range --data-urlencode 'query={project=\"ject-test\",level=\"error\",host=\"prod-data\",env=\"prod\"}' --data-urlencode since=10m | grep -q REDACTED"
systemctl start ject-backup-metrics
check "systemd 작업 로그(ject-backup-metrics·relay) 수집" retry 12 bash -c "curl -fsS -G http://127.0.0.1:3100/loki/api/v1/query_range --data-urlencode 'query={job=\"systemd\", unit=\"ject-backup-metrics.service\"}' --data-urlencode since=30m | grep -q last_run_success"

echo "== Grafana 프로비저닝·알림 =="
GA="admin:$(cat /srv/ject/secrets/grafana_admin_password)"
check "Grafana 외부 주소에서 안 들림" bash -c "! curl -fsS -m 3 http://$DEV_BIND_IP:3000/api/health"
check "익명 접근 거부" bash -c "[ \$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:3000/api/search) = 401 ]"
check "데이터 소스 2개(prom·loki)" bash -c "curl -fsS -u '$GA' http://127.0.0.1:3000/api/datasources | grep -q '\"uid\":\"prom\"' && curl -fsS -u '$GA' http://127.0.0.1:3000/api/datasources | grep -q '\"uid\":\"loki\"'"
check "Prometheus 데이터 소스 동작" bash -c "curl -fsS -u '$GA' 'http://127.0.0.1:3000/api/datasources/uid/prom/health' | grep -qi ok"
check "Loki 데이터 소스 동작" bash -c "curl -fsS -u '$GA' 'http://127.0.0.1:3000/api/datasources/uid/loki/health' | grep -qi ok"
N_RULES=$(curl -fsS -u "$GA" http://127.0.0.1:3000/api/v1/provisioning/alert-rules | python3 -c 'import sys,json;print(len(json.load(sys.stdin)))')
[ "$N_RULES" -ge 15 ] && ok "알림 규칙 $N_RULES개 적재" || bad "알림 규칙 $N_RULES개"
N_DASH=$(curl -fsS -u "$GA" 'http://127.0.0.1:3000/api/search?type=dash-db' | python3 -c 'import sys,json;print(len(json.load(sys.stdin)))')
[ "$N_DASH" -ge 3 ] && ok "대시보드 $N_DASH개" || bad "대시보드 $N_DASH개"
check "연락처(webhook → 중계기)" bash -c "curl -fsS -u '$GA' http://127.0.0.1:3000/api/v1/provisioning/contact-points | grep -q '127.0.0.1:9095/grafana'"
# 실제 규칙 평가 → 중계기까지: 백업 실패(ject_backup_last_run_success=0, for 0s)가 울려야 한다.
check "백업 실패 알림이 중계기에 도착" retry 36 bash -c "journalctl -u ject-alert-relay --since '-15 min' --no-pager | grep -q '운영 DB 백업 실패'"
check "서버 지표 끊김 알림(시험 호스트엔 prod-app 없음)" retry 36 bash -c "journalctl -u ject-alert-relay --since '-15 min' --no-pager | grep -q '서버 지표 끊김'"
check "중계 메시지에 비밀값 없음" bash -c "! journalctl -u ject-alert-relay --since '-15 min' --no-pager | grep -qF \"$PUSH\""

echo "== 정리 =="
docker compose -f /tmp/ject-test.yaml down >/dev/null 2>&1 || true
docker rm -f e2e-be >/dev/null 2>&1 || true
echo "결과: PASS=$PASS FAIL=$FAIL"
[ "$FAIL" -eq 0 ]
