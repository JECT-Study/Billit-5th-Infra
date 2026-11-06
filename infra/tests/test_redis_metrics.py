"""정적/Compose 구성만 시험. Docker daemon·Redis·실서버 실행 없음."""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import unittest

INFRA = Path(__file__).resolve().parents[1]
ALLOY = INFRA / 'observability/alloy/redis.alloy.example'
OVERLAY = INFRA / 'compose/agent-redis.yaml'


class RedisMetricsTests(unittest.TestCase):
    def test_private_exporter_and_pipeline(self):
        text = ALLOY.read_text()
        self.assertIn('redis_addr          = sys.env("JECT_REDIS_METRICS_ADDR")', text)
        self.assertIn('redis_user          = sys.env("JECT_REDIS_METRICS_USER")', text)
        self.assertIn('redis_password_file = "/run/secrets/redis_metrics_password"', text)
        for name in ('export_key_values', 'export_client_list', 'set_client_name'):
            self.assertRegex(text, rf'\b{name}\s*=\s*false')
        for name in ('check_keys', 'check_single_keys', 'check_key_groups', 'check_streams',
                     'check_single_streams', 'count_keys', 'script_path', 'script_paths', 'redis_password'):
            self.assertNotRegex(text, rf'\b{name}\s*=')
        self.assertIn('prometheus.exporter.redis.ject.targets', text)
        self.assertIn('job_name        = "integrations/redis"', text)
        self.assertIn('prometheus.relabel.host.receiver', text)
        self.assertEqual(ALLOY.suffix, '.example')
        installer = (INFRA / 'scripts/install-role.sh').read_text()
        self.assertNotIn('redis.alloy', installer)

    def test_required_inputs_no_secret_value_environment(self):
        text = OVERLAY.read_text()
        for name in ('ADDR', 'USER', 'CONFIG_FILE', 'PASSWORD_FILE'):
            self.assertIn('${JECT_REDIS_METRICS_' + name + ':?', text)
        self.assertIn('read_only: true', text)
        self.assertIn('create_host_path: false', text)
        self.assertNotIn('REDIS_PASSWORD:', text)
        self.assertNotIn('ports:', text)

    @unittest.skipUnless(shutil.which('docker'), 'Docker Compose CLI 미설치; 설치하지 않음')
    def test_compose_merge_and_required_inputs(self):
        env = {'PATH': os.environ['PATH'], 'HOME': os.environ['HOME'],
               'JECT_HOST': 'test', 'JECT_ENV': 'dev', 'OBS_PROM_URL': 'http://localhost/prom',
               'OBS_LOKI_URL': 'http://localhost/loki',
               'JECT_REDIS_METRICS_ADDR': 'redis://127.0.0.1:6379',
               'JECT_REDIS_METRICS_USER': 'synthetic-test-user',
               'JECT_REDIS_METRICS_CONFIG_FILE': str(ALLOY),
               'JECT_REDIS_METRICS_PASSWORD_FILE': '/nonexistent/synthetic-password-file'}
        command = ['docker', 'compose', '-f', str(INFRA / 'compose/agent.yaml'),
                   '-f', str(OVERLAY), 'config', '--format', 'json']
        result = subprocess.run(command, env=env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        config = json.loads(result.stdout)
        alloy = config['services']['alloy']
        self.assertEqual(alloy['network_mode'], 'host')
        self.assertEqual(alloy['image'], 'grafana/alloy:v1.20.1')
        self.assertEqual({s['source'] for s in alloy['secrets']}, {'obs_push_password', 'redis_metrics_password'})
        volume = next(v for v in alloy['volumes'] if v['target'] == '/etc/alloy/redis.alloy')
        self.assertTrue(volume['read_only'])
        for name in ('ADDR', 'USER', 'CONFIG_FILE', 'PASSWORD_FILE'):
            with self.subTest(missing=name):
                missing = {k: v for k, v in env.items() if k != 'JECT_REDIS_METRICS_' + name}
                self.assertNotEqual(subprocess.run(command, env=missing, capture_output=True).returncode, 0)


if __name__ == '__main__':
    unittest.main()
