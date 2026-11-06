import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest import mock
import subprocess

SPEC = importlib.util.spec_from_file_location('redis_metrics_install', Path(__file__).resolve().parents[1] / 'scripts/ject-redis-metrics.py')
m = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m)


class FakeRedis:
    def __init__(self):
        self.user = None
        self.calls = []
        self.fail_create = False

    def command(self, *args, allow_error=False):
        self.calls.append(args)
        if args[:2] == ('ACL', 'GETUSER'):
            return ['flags', ['on'], 'passwords', ['default-hash']] if args[2] == 'default' else self.user
        if args[:2] == ('ACL', 'SETUSER'):
            if self.fail_create:
                raise m.SafeError('synthetic create failure')
            self.user = ['passwords', [args[-1][1:]]]
            return 'OK'
        if args[:2] == ('ACL', 'DELUSER'):
            self.user = None
            return 1
        if args[:2] == ('ACL', 'DRYRUN'):
            return 'OK' if args[3] in ('PING', 'INFO') else {'error': 'NOPERM'}
        if args[0] == 'INFO':
            return 'run_id:unchanged\r\n'
        raise AssertionError(args)


class RedisInstallTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.secret = self.root / 'srv/ject/secrets'
        self.secret.mkdir(parents=True)
        self.base = b'requirepass synthetic-admin\nmaxmemory 8mb\nmaxmemory-policy allkeys-lru\n'
        self.conf = self.secret / 'redis.conf'
        self.conf.write_bytes(self.base)
        self.conf.chmod(0o600)  # 비root 로컬 시험. 운영0400은 root 설치기가 inode 그대로 쓴다.
        (self.secret / 'redis_password').write_text('synthetic-admin')
        (self.secret / 'redis_password').chmod(0o400)
        self.redis = FakeRedis()

    def test_install_preserves_original_bytes_inode_mode_and_default(self):
        inode = self.conf.stat().st_ino
        password = m.install_acl(self.root, self.redis)
        self.assertEqual(m.split_config(self.conf.read_bytes()), (self.base, m.managed_block(password)))
        self.assertEqual(self.conf.stat().st_ino, inode)
        self.assertEqual(self.conf.stat().st_mode & 0o777, 0o600)
        self.assertNotIn(password, self.conf.read_bytes())
        self.assertFalse(any(c[:3] == ('ACL', 'SETUSER', 'default') for c in self.redis.calls))
        self.assertNotIn('+config|get', m.RULES)
        self.assertNotIn('+slowlog|get', m.RULES)

    def test_readonly_parent_mount_gets_empty_nested_target_only(self):
        m.ensure_mountpoint(self.root)
        p = self.root / 'redis.alloy'
        self.assertEqual(p.read_bytes(), b'')
        inode = p.stat().st_ino
        m.ensure_mountpoint(self.root)
        self.assertEqual(p.stat().st_ino, inode)
        p.write_text('existing configuration')
        with self.assertRaises(m.SafeError):
            m.ensure_mountpoint(self.root)
        self.assertEqual(p.read_text(), 'existing configuration')
        p.unlink()
        p.symlink_to(self.conf)
        with self.assertRaises(m.SafeError):
            m.ensure_mountpoint(self.root)

    def test_failed_validation_cleans_exact_owned_container_and_stays_failed(self):
        calls = []
        def run(args, **kwargs):
            calls.append(args)
            if 'validate' in args:
                raise subprocess.CalledProcessError(1, args)
            return subprocess.CompletedProcess(args, 0, stdout='', stderr='')
        with mock.patch.object(m.subprocess, 'run', side_effect=run):
            with self.assertRaises(subprocess.CalledProcessError):
                m.validate_alloy(['docker', 'compose'])
        owned = calls[0][calls[0].index('--name') + 1]
        self.assertTrue(owned.startswith('ject-redis-validate-'))
        self.assertEqual(calls[1], ['docker', 'rm', '-fv', owned])
        self.assertEqual(calls[2][-1], 'name=^/' + owned + '$')
        self.assertFalse(any('up' in c for c in calls))

    def test_validation_cleanup_listing_failure_is_not_success(self):
        def run(args, **kwargs):
            if 'container' in args:
                raise subprocess.CalledProcessError(1, args)
            return subprocess.CompletedProcess(args, 0, stdout='', stderr='')
        with mock.patch.object(m.subprocess, 'run', side_effect=run):
            with self.assertRaises(subprocess.CalledProcessError):
                m.validate_alloy(['docker', 'compose'])

    def test_idempotent_install_and_exact_remove(self):
        first = m.install_acl(self.root, self.redis)
        self.assertEqual(m.install_acl(self.root, self.redis), first)
        m.remove_acl(self.root, self.redis)
        self.assertEqual(self.conf.read_bytes(), self.base)
        self.assertIsNone(self.redis.user)

    def test_create_failure_rolls_back_only_managed_addition(self):
        self.redis.fail_create = True
        with self.assertRaises(m.SafeError):
            m.install_acl(self.root, self.redis)
        self.assertEqual(self.conf.read_bytes(), self.base)

    def test_existing_unmanaged_user_is_not_overwritten(self):
        self.redis.user = ['passwords', ['other-hash']]
        with self.assertRaises(m.SafeError):
            m.install_acl(self.root, self.redis)
        self.assertEqual(self.conf.read_bytes(), self.base)

    def test_aclfile_include_and_password_mismatch_are_rejected(self):
        for config in (self.base + b'aclfile /data/users.acl\n', self.base + b'include /data/other.conf\n',
                       self.base.replace(b'synthetic-admin', b'other')):
            with self.subTest(config=config):
                with self.assertRaises(m.SafeError):
                    m.inspect_config(config, b'synthetic-admin')

    def test_remove_does_not_discard_unrelated_later_edits(self):
        m.install_acl(self.root, self.redis)
        changed = self.conf.read_bytes() + b'maxclients 80\n'
        self.conf.write_bytes(changed)
        with self.assertRaises(m.SafeError):
            m.remove_acl(self.root, self.redis)
        self.assertEqual(self.conf.read_bytes(), changed)


if __name__ == '__main__':
    unittest.main()
