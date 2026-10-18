#!/usr/bin/env bash
# 폐기 가능한 Linux 컨테이너 전용. 실제 배포 스크립트의 잠금·대기를 검증한다.
# docker run --rm --network none -v "$PWD/infra:/source:ro" ubuntu:24.04 bash /source/tests/deploy-queue.sh
set -euo pipefail
[[ -f /.dockerenv && ! -e /etc/ject && ! -e /srv/ject ]] || {
  echo '새 시험 컨테이너에서만 실행하세요' >&2; exit 1;
}
mkdir -p /etc/ject /srv/ject/app /opt/ject/compose /run/lock /tmp/bin
touch /opt/ject/compose/prod-app.yaml
printf 'ALLOWED_IMAGE_PREFIX=ghcr.io/test/\nDEPLOY_LOCK_TIMEOUT=10\n' > /etc/ject/deploy.conf
cat > /tmp/bin/docker <<'MOCK'
#!/usr/bin/env bash
set -euo pipefail
case "$*" in
  'image inspect '*) exit 0 ;;
  'image ls '*) exit 0 ;;
  'inspect '*) echo healthy ;;
  'exec '*) exit 0 ;;
  *' config -q') exit 0 ;;
  *' ps -q '*) echo test-container ;;
  *' up -d '*)
    # 두 배포가 실제 교체 구간에 함께 들어오면 실패한다.
    mkdir /tmp/deploy-active
    sleep 1
    rmdir /tmp/deploy-active
    ;;
  *) echo "예상하지 않은 docker 호출: $*" >&2; exit 2 ;;
esac
MOCK
printf '#!/usr/bin/env bash\nexit 0\n' > /tmp/bin/curl
chmod +x /tmp/bin/docker /tmp/bin/curl
export PATH="/tmp/bin:$PATH"
image="ghcr.io/test/ject-app@sha256:$(printf '%064d' 0)"

( exec 9>/run/lock/ject-deploy-prod.lock; flock 9; touch /tmp/locked; sleep 3 ) &
holder=$!
until [[ -f /tmp/locked ]]; do sleep 0.1; done
bash /source/scripts/ject-deploy deploy prod be "$image" test > /tmp/be.log 2>&1 &
be=$!
bash /source/scripts/ject-deploy deploy prod fe "$image" test > /tmp/fe.log 2>&1 &
fe=$!
sleep 0.5
[[ ! -s /srv/ject/app/deploy-history.jsonl ]]
wait "$holder"
wait "$be" || { cat /tmp/be.log; exit 1; }
wait "$fe" || { cat /tmp/fe.log; exit 1; }
[[ $(grep -c '"result":"success"' /srv/ject/app/deploy-history.jsonl) -eq 2 ]]
grep -q '^JECT_BE_IMAGE=' /srv/ject/app/release.env
grep -q '^JECT_FE_IMAGE=' /srv/ject/app/release.env
echo 'PASS: BE·FE 배포는 잠금 해제까지 기다리고 순차적으로 성공'

cp /srv/ject/app/release.env /tmp/before.env
cp /srv/ject/app/deploy-history.jsonl /tmp/before.jsonl
echo 'DEPLOY_LOCK_TIMEOUT=1' >> /etc/ject/deploy.conf
rm /tmp/locked
( exec 9>/run/lock/ject-deploy-prod.lock; flock 9; touch /tmp/locked; sleep 3 ) &
holder=$!
until [[ -f /tmp/locked ]]; do sleep 0.1; done
if bash /source/scripts/ject-deploy deploy prod be "$image" test > /tmp/timeout.log 2>&1; then
  echo 'FAIL: 잠금 대기 제한을 무시함'; exit 1
fi
grep -q '기다렸지만 끝나지 않았다' /tmp/timeout.log
cmp /tmp/before.env /srv/ject/app/release.env
cmp /tmp/before.jsonl /srv/ject/app/deploy-history.jsonl
wait "$holder"
echo 'PASS: 대기 시간 초과 시 이미지와 배포 이력을 변경하지 않음'
