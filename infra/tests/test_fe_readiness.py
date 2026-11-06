"""운영 경로 접근 없이 ready_checks 셸 함수를 mock으로 실행."""
from pathlib import Path
import os
import subprocess
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/ject-deploy'


def routing_preflight(env='dev', upstream='', rendered='', config_ok=True, service='fe'):
    source = SCRIPT.read_text()
    fn = source[source.index('fe_routing_preflight() {'):source.index('\nready_checks() {')]
    harness = r'''
set -euo pipefail
log() { echo "$*"; }
docker() { [ "$CONFIG_OK" = true ] || return 1; printf '%s\n' "$RENDERED"; }
GATEWAY=synthetic-gateway
'''
    return subprocess.run(['bash', '-c', harness + '\n' + fn + '\nfe_routing_preflight "$SERVICE"'],
                          env={**os.environ, 'ENVN': env, 'SERVICE': service,
                               'DEV_FE_UPSTREAM': upstream, 'PROD_FE_UPSTREAM': upstream,
                               'RENDERED': rendered, 'CONFIG_OK': str(config_ok).lower()},
                          capture_output=True, text=True, timeout=5)


def invoke(env='dev', fail='', service='fe', health='healthy'):
    source=SCRIPT.read_text()
    fn=source[source.index('ready_checks() {'):source.index('\nswitch_to() {')]
    harness=r'''
set -euo pipefail
compose() { echo synthetic-container; }
log() { echo "$*"; }
docker() {
 if [ "$1" = inspect ]; then echo "${HEALTH:-healthy}"; return; fi
 echo "DOCKER:$*"
 [ "$FAIL" != direct ]
}
curl() { echo "CURL:$*" >&2; [ "$FAIL" != gateway ]; }
sleep() { :; }
GATEWAY=synthetic-gateway
DEV_BIND_IP=127.0.0.1
PROD_DOMAIN=
'''
    return subprocess.run(['bash','-c',harness+'\n'+fn+'\nready_checks '+service],
                          env={**os.environ,'ENVN':env,'FAIL':fail,'HEALTH':health},capture_output=True,text=True,timeout=5)


class FeReadinessTests(unittest.TestCase):
    def test_first_fe_deploy_requires_routing_before_image_switch(self):
        result = routing_preflight()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('FE 라우팅', result.stdout)
        source = SCRIPT.read_text()
        self.assertLess(source.index('fe_routing_preflight "$SVC" ||'), source.index('pull_image ||'))
        self.assertLess(source.index('fe_routing_preflight "$SVC" ||'), source.index('if switch_to "$SVC"'))

    def test_fe_routing_requires_rendered_config_for_both_environments(self):
        for env in ('dev', 'prod'):
            with self.subTest(env=env):
                self.assertEqual(routing_preflight(env, 'fe:3000', '    set $web_up fe:3000;').returncode, 0)
                self.assertNotEqual(routing_preflight(env, 'fe:3000', 'set $web_up be:8080;').returncode, 0)
                self.assertNotEqual(routing_preflight(env, 'fe:3000', '# set $web_up fe:3000;').returncode, 0)
                self.assertNotEqual(routing_preflight(env, 'fe:3000', 'set $web_up fe:3000;', False).returncode, 0)

    def test_be_does_not_require_fe_route(self):
        self.assertEqual(routing_preflight(service='be', config_ok=False).returncode, 0)

    def test_dev_checks_direct_and_gateway(self):
        result=invoke()
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn('http://fe:3000/healthz',result.stdout)
        self.assertIn('http://127.0.0.1:8080/healthz',result.stderr)

    def test_direct_failure_prevents_success(self):
        self.assertNotEqual(invoke(fail='direct').returncode,0)

    def test_gateway_failure_prevents_success(self):
        self.assertNotEqual(invoke(fail='gateway').returncode,0)

    def test_unhealthy_stops_before_gateway(self):
        result=invoke(health='unhealthy')
        self.assertNotEqual(result.returncode,0)
        self.assertNotIn('CURL:',result.stderr)
        self.assertNotIn('DOCKER:',result.stdout)

    def test_be_existing_readiness_paths_are_preserved(self):
        result=invoke(service='be')
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn('http://be:8080/readyz',result.stdout)
        self.assertIn('http://127.0.0.1:8080/readyz',result.stderr)

    def test_prod_without_tls_checks_gateway(self):
        result=invoke(env='prod')
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn('http://127.0.0.1/healthz',result.stderr)

if __name__=='__main__':unittest.main()
