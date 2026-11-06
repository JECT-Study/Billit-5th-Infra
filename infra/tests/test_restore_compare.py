"""복원 비교 Python 본문만 합성 subprocess로 시험. Docker/DB/OCI 접근 없음."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/ject-pg-restore-test'


class RestoreCompareTests(unittest.TestCase):
    def run_compare(self, code=0, stdout='3', tables=None, db='test'):
        source = SCRIPT.read_text()
        block = source.split('STAGE=compare\n', 1)[1].split("<<'PY'\n", 1)[1].split('\nPY\n', 1)[0]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'compare.py').write_text(block)
            (root / 'subprocess.py').write_text('''import os, json
class Result:
    returncode = int(os.environ['MOCK_CODE'])
    stdout = os.environ['MOCK_STDOUT']
def run(*args, **kwargs):
    with open(os.environ["CALL_LOG"], "w") as stream:
        json.dump(args[0], stream)
    return Result()
''')
            manifest = root / 'manifest.json'
            manifest.write_text(json.dumps({'databases': [{'name': db, 'tables': tables if tables is not None else {'public.t': 3}}]}))
            result = subprocess.run(['python3', str(root / 'compare.py'), str(manifest), 'fake-container', 'synthetic_restore'],
                                    env={**os.environ, 'CALL_LOG': str(root / 'calls.json'), 'MOCK_CODE': str(code), 'MOCK_STDOUT': stdout},
                                    capture_output=True, text=True)
            result.command = json.loads((root / "calls.json").read_text()) if (root / "calls.json").exists() else None
            return result

    def test_database_name_cannot_override_connection_parameters(self):
        db = "dbname=other host=external ' \\"
        result = self.run_compare(db=db)
        self.assertEqual(result.returncode, 0)
        value = result.command[result.command.index('-d') + 1]
        self.assertEqual(value, "dbname='" + db.replace("\\", "\\\\").replace("'", "\\'") + "' host='/var/run/postgresql'")

    def test_matching_count_passes(self):
        self.assertEqual(self.run_compare().returncode, 0)

    def test_failed_query_cannot_pass_even_with_matching_stdout(self):
        self.assertNotEqual(self.run_compare(code=1, stdout='3').returncode, 0)

    def test_count_mismatch_and_invalid_output_fail(self):
        for value in ('4', '', 'not-a-count'):
            with self.subTest(value=value):
                self.assertNotEqual(self.run_compare(stdout=value).returncode, 0)

    def test_existing_empty_database_behavior_is_preserved(self):
        self.assertEqual(self.run_compare(tables={}).returncode, 0)

    def test_manifest_table_sql_injection_is_rejected(self):
        for table in ('public.t; SELECT 1', 'public.t --comment', 'public.t WHERE true', 'public.t\n;SELECT 1'):
            with self.subTest(table=table):
                self.assertNotEqual(self.run_compare(tables={table: 3}).returncode, 0)

    def test_quoted_identifier_is_allowed(self):
        self.assertEqual(self.run_compare(tables={'"schema space"."table ""quote"""': 3}).returncode, 0)


if __name__ == '__main__':
    unittest.main()
