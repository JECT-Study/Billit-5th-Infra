import contextlib
import importlib.util
import io
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / 'observability/grafana/render-alert-contact.py'
SPEC = importlib.util.spec_from_file_location('contact', SCRIPT)
m = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m)
FAKE = 'https://discord.com/api/webhooks/123456789012345678/' + 'test_token_' * 5
SOURCE = m.SOURCE.read_text()


def as_root(value):
    fields = list(value)
    fields[4] = 0
    return os.stat_result(fields)


class ContactTests(unittest.TestCase):
    def test_preserves_source_and_policy_exactly(self):
        result = m.render(SOURCE, FAKE)
        self.assertEqual(m.base_content(result), SOURCE)
        self.assertEqual(result.count('uid: ject-relay'), 1)
        self.assertEqual(result.count('uid: ject-discord'), 1)
        self.assertIn('use_discord_username: true', result)
        self.assertNotIn('secure_settings', result)
        self.assertEqual(result.split('policies:\n')[1], SOURCE.split('policies:\n')[1])

    def test_rejects_changed_contact_and_unapproved_url(self):
        with self.assertRaises(ValueError): m.render(SOURCE.replace('9095', '9999'), FAKE)
        for bad in (FAKE+'?query=x', FAKE.replace('discord.com', 'discord.com.evil'), FAKE+'\nurl: evil'):
            with self.subTest(bad=bad), self.assertRaises(ValueError): m.render(SOURCE, bad)

    def test_secret_permissions_symlink_and_no_value_errors(self):
        with tempfile.TemporaryDirectory() as temp:
            secret = Path(temp).resolve() / 'secret'
            secret.write_text(FAKE+'\n'); secret.chmod(0o600)
            original = os.fstat
            with patch.object(m.os, 'fstat', side_effect=lambda fd: as_root(original(fd))):
                self.assertEqual(m.read_secret(secret), FAKE)
                secret.chmod(0o644)
                with self.assertRaises(ValueError) as exc: m.read_secret(secret)
                self.assertNotIn(FAKE, str(exc.exception))
            link = secret.with_name('link'); link.symlink_to(secret)
            with self.assertRaises(ValueError): m.read_secret(link)

    def test_atomic_output_permissions_and_drift_refusal(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp).resolve() / 'contact-points.yaml'
            original = Path.stat
            with patch.object(m, 'OUTPUT', target), patch.object(Path, 'stat', autospec=True,
                    side_effect=lambda path, **kw: as_root(original(path, **kw))), \
                    patch.object(m.os, 'fchown') as chown:
                m.write_output(target, SOURCE, m.render(SOURCE, FAKE))
                chown.assert_called_once()
                self.assertEqual(chown.call_args.args[1:], (0, 472))
                self.assertEqual(target.stat().st_mode & 0o777, 0o640)
                m.write_output(target, SOURCE, m.render(SOURCE, FAKE.replace('test', 'next')))
                changed = target.read_text().replace('repeat_interval: 4h', 'repeat_interval: 8h')
                target.write_text(changed)
                with self.assertRaises(ValueError): m.write_output(target, SOURCE, m.render(SOURCE, FAKE))
                self.assertEqual(target.read_text(), changed)
                self.assertFalse(list(target.parent.glob('.contact-*')))

    def test_cli_default_dry_run_does_not_expose_secret(self):
        output = io.StringIO()
        with patch('sys.argv', [str(SCRIPT)]), patch.object(m, 'read_secret', return_value=FAKE), \
                patch.object(m, 'write_output') as writer, contextlib.redirect_stdout(output):
            m.main()
        writer.assert_not_called()
        self.assertNotIn(FAKE, output.getvalue())
        self.assertIn('발송 없음', output.getvalue())

    def test_failure_does_not_print_exception_secret(self):
        with patch('sys.argv', [str(SCRIPT)]), patch.object(m, 'read_secret', side_effect=ValueError(FAKE)):
            with self.assertRaises(SystemExit) as exc: m.main()
        self.assertNotIn(FAKE, str(exc.exception))


if __name__ == '__main__': unittest.main()
