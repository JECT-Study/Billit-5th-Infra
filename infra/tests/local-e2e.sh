#!/usr/bin/env bash
# 로컬 통합 시험 (Ubuntu 24.04 ARM64 + Docker 환경, root). 실제 OCI 대신 fake-oci.py를 쓴다.
# 운영 데이터(prod-data)·운영 앱(prod-app) 역할을 한 호스트에 설치해
# 백업·보존·복원, 배포·healthcheck·자동 복구·롤백·동시 배포 차단, 영속성을 확인한다.
#   sudo bash infra/tests/local-e2e.sh
set -euo pipefail
INFRA="$(cd "$(dirname "$0")/.." && pwd)"
PASS=0; FAIL=0
ok()   { echo "PASS: $*"; PASS=$((PASS+1)); }
bad()  { echo "FAIL: $*"; FAIL=$((FAIL+1)); }
check() { local d="$1"; shift; if "$@" >/dev/null 2>&1; then ok "$d"; else bad "$d"; fi; }
HOST_IP="$(hostname -I | awk '{print $1}')"
REG=localhost:5000

echo "== 준비 (이전 시험 상태 초기화: 이 시험 호스트 전용) =="
for pr in ject-prod ject-edge ject-prod-data; do docker compose -p "$pr" down -v --remove-orphans >/dev/null 2>&1 || true; done
docker rm -f reg >/dev/null 2>&1 || true
rm -rf /srv/ject /etc/ject /opt/ject /run/lock/ject-*.lock
mkdir -p /opt/ject/oci-cli/bin
install -m 0755 "$INFRA/tests/fake-oci.py" /opt/ject/oci-cli/bin/oci
export FAKE_OCI_ROOT=/tmp/fake-oci; rm -rf "$FAKE_OCI_ROOT"
mkdir -p /etc/ject /srv/ject/secrets /srv/ject/data/postgres /srv/ject/data/redis /srv/ject/backup-tmp /srv/ject/app/nginx /srv/ject/app/acme /srv/ject/certs
getent group ject-admins >/dev/null || groupadd ject-admins
echo prod-data > /etc/ject/role
bash "$INFRA/scripts/install-role.sh" prod-data e2e
bash "$INFRA/scripts/install-role.sh" prod-app e2e
# 시험: 날짜 기준 보존을 즉시 확인하려고 보존 일수를 0으로 둔다(최신 성공 7개는 항상 남음)
printf 'BUCKET=ject-db-backups\nPREFIX=postgres/prod\nRETAIN_DAYS=0\nRETAIN_MIN=7\n' > /etc/ject/backup.conf
systemctl disable --now ject-pg-backup.timer ject-pg-restore-test.timer ject-certbot-renew.timer >/dev/null 2>&1 || true
printf 'ALLOWED_IMAGE_PREFIX=%s/\nMIN_FREE_PCT=5\nWAIT_TIMEOUT=120\nKEEP_IMAGES=3\n' "$REG" > /etc/ject/deploy.conf

echo "== 운영 데이터 =="
bash /opt/ject/bin/setup-secrets.sh prod-data
echo "DATA_BIND_IP=$HOST_IP" > /srv/ject/data.env
docker compose -p ject-prod-data -f /opt/ject/compose/prod-data.yaml --env-file /srv/ject/data.env up -d --wait
check "postgres healthy" docker compose -p ject-prod-data -f /opt/ject/compose/prod-data.yaml --env-file /srv/ject/data.env ps --status running postgres
# 앱 역할로 접속해 시험 데이터 생성
APP_PW="$(cat /srv/ject/secrets/pg_app_password)"
docker run --rm --network host -e PGPASSWORD="$APP_PW" postgres:17.11-bookworm \
  psql -h "$HOST_IP" -U ject_app -d ject -v ON_ERROR_STOP=1 -qc \
  "CREATE TABLE IF NOT EXISTS trip(id serial primary key, name text); TRUNCATE trip; INSERT INTO trip(name) SELECT 'trip'||g FROM generate_series(1,123) g;"
check "앱 역할로 운영 DB 쓰기" true
check "관리자 비밀번호 없이 접속 거부" bash -c "! docker run --rm --network host postgres:17.11-bookworm psql -h $HOST_IP -U ject_admin -d postgres -c 'select 1' -w"
REDIS_PW="$(cat /srv/ject/secrets/redis_password)"
check "Redis 인증 필요" bash -c "docker run --rm --network host redis:7.4.11-alpine redis-cli -h $HOST_IP ping | grep -q NOAUTH"
check "Redis 인증 후 PONG" bash -c "REDISCLI_AUTH='$REDIS_PW' docker run --rm --network host -e REDISCLI_AUTH redis:7.4.11-alpine redis-cli -h $HOST_IP ping | grep -q PONG"

echo "== 백업 =="
/opt/ject/bin/ject-pg-backup
check "백업 성공 기록" grep -q '"result":"success"' /srv/ject/backup-status/last.json
check "MANIFEST 업로드" bash -c "ls $FAKE_OCI_ROOT/ject-db-backups/postgres/prod/*/MANIFEST.json"
check "MANIFEST 행 수 123" bash -c "grep -qE '\"public.trip\" *: *123' \$(ls $FAKE_OCI_ROOT/ject-db-backups/postgres/prod/*/MANIFEST.json | tail -1)"
check "임시 파일 정리" bash -c "[ -z \"\$(ls -A /srv/ject/backup-tmp)\" ]"
for n in $(seq 1 8); do sleep 1; /opt/ject/bin/ject-pg-backup >/dev/null; done
RUNS=$(ls "$FAKE_OCI_ROOT/ject-db-backups/postgres/prod" | wc -l)
[ "$RUNS" -eq 7 ] && ok "보존: 성공 백업 7개만 유지 ($RUNS)" || bad "보존 개수 $RUNS"
BEFORE=$(ls "$FAKE_OCI_ROOT/ject-db-backups/postgres/prod" | wc -l)
sleep 1
if FAKE_OCI_FAIL=put /opt/ject/bin/ject-pg-backup >/dev/null 2>&1; then bad "업로드 실패가 성공으로 보고됨"; else ok "업로드 실패 시 종료 코드 1"; fi
check "실패 기록" grep -q '"result":"failed"' /srv/ject/backup-status/last.json
AFTER=$(ls "$FAKE_OCI_ROOT/ject-db-backups/postgres/prod" | wc -l)
[ "$AFTER" -ge "$BEFORE" ] && ok "실패 시 기존 백업 보존 ($BEFORE→$AFTER)" || bad "실패 후 백업 감소"
check "last-success 유지" grep -q '"result":"success"' /srv/ject/backup-status/last-success.json
sleep 1
if FAKE_OCI_FAIL=head /opt/ject/bin/ject-pg-backup >/dev/null 2>&1; then bad "검증 실패가 성공으로 보고됨"; else ok "업로드 후 검증 실패 시 종료 코드 1"; fi
check "검증 실패 실행에는 MANIFEST 없음(성공 표식은 검증 뒤에만)" bash -c "for d in $FAKE_OCI_ROOT/ject-db-backups/postgres/prod/*/; do [ -f \$d/MANIFEST.json ] || exit 0; done; exit 1"
mkdir -p "$FAKE_OCI_ROOT/ject-db-backups/postgres/prod/20200101T000000Z" && echo x > "$FAKE_OCI_ROOT/ject-db-backups/postgres/prod/20200101T000000Z/db1.dump"
sleep 1; /opt/ject/bin/ject-pg-backup >/dev/null
check "오래된 불완전 실행 정리" bash -c "[ ! -d $FAKE_OCI_ROOT/ject-db-backups/postgres/prod/20200101T000000Z ]"

echo "== 복원 시험 =="
/opt/ject/bin/ject-pg-restore-test latest
check "복원 성공 기록" grep -q '"result":"success"' /srv/ject/backup-status/restore-last.json
check "복원 컨테이너 정리" bash -c "! docker ps -a --format '{{.Names}}' | grep -qx ject-restore-test"
# 손상 감지: 덤프 1바이트 변조 → 체크섬 실패여야 함
LATEST=$(ls "$FAKE_OCI_ROOT/ject-db-backups/postgres/prod" | sort | tail -1)
for f in "$FAKE_OCI_ROOT/ject-db-backups/postgres/prod/$LATEST"/*.dump; do printf 'x' >> "$f"; done
if /opt/ject/bin/ject-pg-restore-test "$LATEST" >/dev/null 2>&1; then bad "변조된 백업이 복원 성공으로 보고됨"; else ok "변조 백업 체크섬 실패 감지"; fi

echo "== 영속성 =="
docker compose -p ject-prod-data -f /opt/ject/compose/prod-data.yaml --env-file /srv/ject/data.env up -d --force-recreate --wait >/dev/null
CNT=$(docker exec ject-prod-data-postgres-1 psql -U ject_admin -d ject -Atqc 'select count(*) from trip')
[ "$CNT" = 123 ] && ok "컨테이너 재생성 후 데이터 유지 ($CNT)" || bad "재생성 후 행 수 $CNT"

echo "== 배포 =="
docker rm -f reg >/dev/null 2>&1 || true
docker run -d --name reg -p 127.0.0.1:5000:5000 registry:2 >/dev/null
sleep 2
build() {   # tag version [bad]
  local dir; dir=$(mktemp -d)
  docker build -q --build-arg VERSION="$2" -t "$REG/ject/smoke:$1" "$INFRA/smoke-app" >/dev/null
  if [ "${3:-}" = bad ]; then
    printf 'FROM %s\nENV FAIL_READY=1\n' "$REG/ject/smoke:$1" > "$dir/Dockerfile"
    docker build -q -t "$REG/ject/smoke:$1" "$dir" >/dev/null
  fi
  docker push -q "$REG/ject/smoke:$1" >/dev/null
  docker inspect --format '{{index .RepoDigests 0}}' "$REG/ject/smoke:$1"
}
V1=$(build v1 v1); V2=$(build v2 v2-bad bad); V3=$(build v3 v3)
printf 'PG_x %s\n' "" >/dev/null
echo "$APP_PW $REDIS_PW" | bash /opt/ject/bin/setup-secrets.sh prod-app-env "$HOST_IP"
bash /opt/ject/bin/render-nginx.sh edge
docker compose -p ject-edge -f /opt/ject/compose/prod-edge.yaml up -d --wait
/opt/ject/bin/ject-deploy deploy prod be "$V1" e2e && ok "v1 배포" || bad "v1 배포"
check "Nginx 경유 /readyz" curl -fsS http://127.0.0.1/readyz
check "버전 v1" bash -c "curl -fsS http://127.0.0.1/version | grep -qx v1"
check "/actuator 차단" bash -c "[ \$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1/actuator/health) = 404 ]"
if /opt/ject/bin/ject-deploy deploy prod be "$V2" e2e; then bad "readiness 실패 이미지가 성공 처리됨"; else ok "v2(readiness 실패) 거부"; fi
check "자동 복구 후 v1 동작" bash -c "curl -fsS http://127.0.0.1/version | grep -qx v1"
check "rolled_back 기록" grep -q '"result":"rolled_back"' /srv/ject/app/deploy-history.jsonl
/opt/ject/bin/ject-deploy deploy prod be "$V3" e2e && ok "v3 배포" || bad "v3 배포"
check "버전 v3" bash -c "curl -fsS http://127.0.0.1/version | grep -qx v3"
/opt/ject/bin/ject-deploy rollback prod be e2e && ok "수동 롤백 실행" || bad "수동 롤백"
check "롤백 후 v1" bash -c "curl -fsS http://127.0.0.1/version | grep -qx v1"
if /opt/ject/bin/ject-deploy rollback prod be e2e 2>/dev/null; then
  curl -fsS http://127.0.0.1/version | grep -qx v3 && bad "두 번째 롤백이 버린 v3로 돌아감" || ok "두 번째 롤백이 v3로 돌아가지 않음"
else ok "두 번째 롤백: 되돌릴 다른 이미지 없음으로 거부"; fi
check "관리 경로 우회 차단(/v3/api-docs.yaml)" bash -c "[ \$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1/v3/api-docs.yaml) = 404 ]"
check "경로 매개변수 우회 차단(;)" bash -c "[ \$(curl -s -o /dev/null -w '%{http_code}' 'http://127.0.0.1/actuator;x/env') = 400 ]"
check "DB 초기화 로그에 비밀번호 없음" bash -c "! docker logs ject-prod-data-postgres-1 2>&1 | grep -qF \"\$(cat /srv/ject/secrets/pg_app_password)\""
( exec 9>/run/lock/ject-deploy-prod.lock; flock 9; sleep 3 ) &
sleep 1
if /opt/ject/bin/ject-deploy deploy prod be "$V3" e2e; then ok "다른 배포의 잠금 해제 후 배포 성공"; else bad "배포 대기 실패"; fi
wait
echo 'DEPLOY_LOCK_TIMEOUT=1' >> /etc/ject/deploy.conf
( exec 9>/run/lock/ject-deploy-prod.lock; flock 9; sleep 3 ) &
sleep 1
if /opt/ject/bin/ject-deploy deploy prod be "$V1" e2e 2>/dev/null; then bad "잠금 대기 제한 무시"; else ok "잠금 대기 시간 초과 시 거부"; fi
wait
sed -i '/^DEPLOY_LOCK_TIMEOUT=/d' /etc/ject/deploy.conf
check "잠금 시간 초과 시 현재 버전 유지" bash -c "curl -fsS http://127.0.0.1/version | grep -qx v3"
if /opt/ject/bin/ject-deploy deploy prod be "$REG/ject/smoke:v3" e2e 2>/dev/null; then bad "digest 없는 참조 허용"; else ok "digest 없는 이미지 거부"; fi
if /opt/ject/bin/ject-deploy deploy prod be "docker.io/library/nginx@sha256:$(printf '0%.0s' $(seq 64))" e2e 2>/dev/null; then bad "허용 외 레지스트리 허용"; else ok "허용 외 레지스트리 거부"; fi
check "Nginx 재시작 없음(배포 중)" bash -c "[ \$(docker inspect -f '{{.RestartCount}}' ject-edge-nginx-1) = 0 ]"
check "로그 순환 설정" bash -c "docker inspect -f '{{.HostConfig.LogConfig.Config}}' ject-prod-be-1 | grep -q max-size:10m"
check "접근 로그에 쿼리 문자열 없음" bash -c "curl -s 'http://127.0.0.1/readyz?token=SECRET123' >/dev/null; sleep 1; ! docker logs ject-edge-nginx-1 2>&1 | grep -q SECRET123"

echo
echo "결과: PASS=$PASS FAIL=$FAIL"
[ "$FAIL" -eq 0 ]
