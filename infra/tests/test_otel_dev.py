"""OTel 신규 스택의 네트워크/자원 경계와 시작 전 저장소 차단 검사."""
import importlib.util
import json
from pathlib import Path
import subprocess
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('otel_preflight', ROOT / 'observability/otel/preflight.py')
preflight = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(preflight)


class PreflightTests(unittest.TestCase):
    def storage(self, mounted=True, total=1024, free=256, owner=10001, mode=0o40700, same_device=False):
        path = preflight.DATA
        info = SimpleNamespace(st_dev=2, st_uid=owner, st_mode=mode)
        parent = SimpleNamespace(st_dev=2 if same_device else 1)
        statvfs = SimpleNamespace(f_blocks=total, f_bavail=free, f_frsize=preflight.MIB)
        with patch.object(Path, 'is_symlink', return_value=False), patch.object(Path, 'resolve', return_value=path), \
             patch.object(Path, 'is_dir', return_value=True), patch('os.path.ismount', return_value=mounted), \
             patch.object(Path, 'stat', side_effect=lambda *a, **k: info if a[0] == path else parent, autospec=True), \
             patch('os.statvfs', return_value=statvfs):
            return preflight.check_storage(path)

    def test_valid_bounded_mount(self):
        self.assertEqual(self.storage()['total_bytes'], 1024 * preflight.MIB)

    def test_no_mount_or_root_bind_is_refused(self):
        for kw in ({'mounted': False}, {'same_device': True}):
            with self.subTest(kw=kw), self.assertRaises(ValueError): self.storage(**kw)

    def test_unbounded_full_or_insecure_storage_is_refused(self):
        for kw in ({'total': 1025}, {'total': 511}, {'free': 127}, {'owner': 0}, {'mode': 0o40755}, {'mode': 0o40400}):
            with self.subTest(kw=kw), self.assertRaises(ValueError): self.storage(**kw)

    def test_config_paths_require_real_root_owned_readable_files(self):
        path = Path('/opt/ject/otel/proxy.conf')
        with patch.object(Path, 'resolve', autospec=True, side_effect=lambda p: p), \
             patch.object(Path, 'stat', return_value=SimpleNamespace(st_uid=0, st_mode=0o100644)):
            preflight.check_config_files()
        for info in (SimpleNamespace(st_uid=1000, st_mode=0o100644),
                     SimpleNamespace(st_uid=0, st_mode=0o100666),
                     SimpleNamespace(st_uid=0, st_mode=0o40644)):
            with patch.object(Path, 'resolve', autospec=True, side_effect=lambda p: p), \
                 patch.object(Path, 'stat', return_value=info), self.assertRaises(ValueError):
                preflight.check_config_files()



class ComposeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        raw = subprocess.check_output(['docker', 'compose', '-f', str(ROOT / 'compose/otel.yaml'),
                                       'config', '--format', 'json'], text=True)
        cls.config = json.loads(raw)

    def test_isolated_non_public_network_and_no_app_mounts(self):
        self.assertEqual(set(self.config['services']), {'tempo', 'collector', 'proxy'})
        self.assertTrue(self.config['networks']['traces']['internal'])
        self.assertNotIn('internal', self.config['networks']['ingress'])
        for name in ('tempo', 'collector'):
            self.assertEqual(set(self.config['services'][name]['networks']), {'traces'})
            self.assertNotIn('ports', self.config['services'][name])
        self.assertEqual(set(self.config['services']['proxy']['networks']), {'traces', 'ingress'})
        for svc in self.config['services'].values():
            self.assertEqual(svc['restart'], 'no')
            self.assertTrue(svc['read_only'])
            for port in svc.get('ports', []): self.assertEqual(port['host_ip'], '127.0.0.1')
            for mount in svc['volumes']:
                self.assertFalse(mount['bind']['create_host_path'])
                self.assertNotIn('docker.sock', mount['source'])

    def test_process_and_log_bounds(self):
        for name, memory in [('tempo', 512), ('collector', 256), ('proxy', 64)]:
            svc = self.config['services'][name]
            self.assertEqual(int(svc['mem_limit']), memory * preflight.MIB)
            self.assertLessEqual(float(svc['cpus']), 0.35)
            self.assertEqual(svc['pids_limit'], 32 if name == 'proxy' else 128)
            self.assertEqual(svc['logging']['options'], {'max-file': '2', 'max-size': '5m'})
            self.assertIn('@sha256:', svc['image'])

    def test_proxy_uses_only_fixed_internal_upstreams(self):
        config = (ROOT / 'observability/otel/proxy.conf').read_text()
        self.assertIn('client_max_body_size 1m;', config)
        self.assertIn('server tempo:3200 resolve;', config)
        self.assertIn('server collector:4318 resolve;', config)
        self.assertIn('server collector:12345 resolve;', config)
        self.assertNotIn('proxy_pass $', config)
        self.assertIn('location = /v1/traces', config)
        self.assertIn('access_log off;', config)

    def test_systemd_preflight_and_mount_order(self):
        unit = (ROOT / 'observability/otel/ject-otel.service').read_text()
        self.assertIn('RequiresMountsFor=/srv/ject/observability/tempo', unit)
        self.assertIn('ExecStartPre=/usr/bin/python3 /opt/ject/otel/preflight.py', unit)
        self.assertIn('up --abort-on-container-exit', unit)
        self.assertNotIn('down -v', unit)


if __name__ == '__main__': unittest.main()
