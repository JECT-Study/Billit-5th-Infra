"""다운로드한 합성 MANIFEST 경계 검사. 실제 백업/OCI 접근 없음."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/ject-pg-restore-test'


class RestoreManifestTests(unittest.TestCase):
    def check(self, mutate=lambda m, p: None, optimize=False):
        block = SCRIPT.read_text().split("STAGE=checksum\n", 1)[1].split("\nSTAGE=start", 1)[0]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for file in ('globals.sql', 'db1.dump'):
                (root / file).write_bytes(b'synthetic')
            digest = hashlib.sha256(b'synthetic').hexdigest()
            manifest = {'globals': {'file': 'globals.sql', 'sha256': digest}, 'databases': [
                {'name': 'dbname=odd host=external', 'file': 'db1.dump', 'sha256': digest, 'tables': {}}]}
            mutate(manifest, root)
            (root / 'MANIFEST.json').write_text(json.dumps(manifest))
            return subprocess.run(['bash', '-c', block], env={**os.environ, 'D': str(root),
                                  'PYTHONOPTIMIZE': '1' if optimize else ''}, capture_output=True).returncode

    def test_existing_format_and_literal_database_name_pass(self):
        self.assertEqual(self.check(), 0)

    def test_unsafe_paths_hashes_names_and_duplicates_fail(self):
        for key, value in [('file', '../outside.dump'), ('file', '/tmp/db1.dump'),
                           ('sha256', 'wrong'), ('name', 'template1'), ('name', 'bad\nname'),
                           ('tables', {'public.t': True})]:
            with self.subTest(key=key, value=value):
                self.assertNotEqual(self.check(lambda m, p: m['databases'][0].update({key: value})), 0)
        self.assertNotEqual(self.check(lambda m, p: m['databases'].append(m['databases'][0].copy())), 0)

    def test_symlink_is_rejected(self):
        def mutate(m, root):
            (root / 'db1.dump').unlink()
            (root / 'db1.dump').symlink_to(root / 'globals.sql')
        self.assertNotEqual(self.check(mutate), 0)

    def test_optimization_environment_cannot_disable_validation(self):
        self.assertEqual(self.check(optimize=True), 0)
        for mutation in [lambda m, p: m['databases'][0].update(sha256='0' * 64),
                         lambda m, p: m['databases'][0].update(name='template1')]:
            self.assertNotEqual(self.check(mutation, optimize=True), 0)
