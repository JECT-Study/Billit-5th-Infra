"""실제 restore 셸 블록과 종료 기록을 mock Docker로 검증. DB/OCI 접근 없음."""
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/ject-pg-restore-test'


class RestoreGlobalsTests(unittest.TestCase):
    def run_globals(self, failure=0, cleanup_failure=0, remaining="", list_failure=0):
        source = SCRIPT.read_text()
        finish = source.split('finish() {', 1)[1].split('\nexec 9>', 1)[0]
        block = source.split('STAGE=start\n', 1)[1].split('mapfile -t ROWS', 1)[0]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            work = root / 'work'
            work.mkdir()
            (work / "globals.sql").write_text("CREATE ROLE ject_admin;\nALTER ROLE ject_admin WITH SUPERUSER;\n")
            docker = root / 'docker'
            docker.write_text('''#!/bin/sh
case "$1" in
 run)
  for arg do
    case "$arg" in POSTGRES_USER=*) printf '%s\\n' "$arg" >> "$CALLS";; esac
  done
  ;;
 exec)
  printf '%s\\n' "$*" >> "$CALLS"
  case "$3" in
   pg_isready) exit 0;;
   psql) echo 'SYNTHETIC_PRIVATE_SQL' >&2; exit "$MOCK_FAILURE";;
   *) exit 99;;
  esac
  ;;
 rm) exit "$MOCK_REMOVE_FAILURE";;
 container) printf '%s\\n' "$MOCK_REMAINING"; exit "$MOCK_LIST_FAILURE";;
 *) exit 99;;
esac
''')
            docker.chmod(0o700)
            # finish는 temp 하위의 WORK/STATUS_DIR만 정리·기록한다.
            script = ('set -euo pipefail\nSTART=$(date +%s)\nDETAIL=""\n'
                      + 'finish() {' + finish + '\ntrap finish EXIT\nSTAGE=start\n' + block
                      + '\nprintf reached > "$NEXT_MARKER"\nSTAGE=complete\n')
            env = {**os.environ, 'PATH': str(root) + ':' + os.environ['PATH'],
                   'NAME': 'synthetic-container', 'D': str(work), 'WORK': str(work),
                   'PG_IMAGE': 'unused-synthetic-image', 'STATUS_DIR': str(root / 'status'),
                   'RUN_ID': 'synthetic-run', 'MOCK_FAILURE': str(failure),
                   'MOCK_REMOVE_FAILURE': str(cleanup_failure), 'MOCK_REMAINING': remaining,
                   'MOCK_LIST_FAILURE': str(list_failure),
                   'NEXT_MARKER': str(root / 'next'), 'CALLS': str(root / 'calls')}
            result = subprocess.run(['bash', '-c', script], env=env, capture_output=True, text=True)
            history = json.loads((root / 'status/restore-last.json').read_text())
            calls = (root / 'calls').read_text()
            return result, history, calls, (root / 'next').exists()

    def test_bootstrap_filter_requires_one_exact_declaration(self):
        source = SCRIPT.read_text()
        block = source.split("<<'PYGLOBALS'\n", 1)[1].split('\nPYGLOBALS', 1)[0]
        for text, success in [('CREATE ROLE ject_admin;\nALTER ROLE ject_admin WITH SUPERUSER;\n', True),
                              ('CREATE ROLE someone_else;\n', False),
                              ('CREATE ROLE ject_admin;\nCREATE ROLE ject_admin;\n', False),
                              ('CREATE ROLE ject_admin; SELECT 1;\n', False)]:
            with self.subTest(text=text), tempfile.TemporaryDirectory() as tmp:
                src, dst = Path(tmp) / 'in.sql', Path(tmp) / 'out.sql'
                src.write_text(text)
                result = subprocess.run(['python3', '-c', block, str(src), str(dst)], capture_output=True)
                self.assertEqual(result.returncode == 0, success)
                self.assertEqual(src.read_text(), text)
                if success:
                    self.assertEqual(dst.read_text(), 'ALTER ROLE ject_admin WITH SUPERUSER;\n')

    def test_same_safe_bootstrap_used_for_init_readiness_and_globals(self):
        result, history, calls, reached = self.run_globals()
        self.assertEqual(result.returncode, 0, result.stderr)
        role = calls.splitlines()[0].split('=', 1)[1]
        self.assertEqual(role, 'ject_admin')
        self.assertEqual(calls.count('-U ' + role), 3)
        self.assertIn('-qX -v ON_ERROR_STOP=1 -f /restore-globals.sql', calls)
        self.assertTrue(reached)
        self.assertEqual(history['result'], 'success')
        self.assertEqual(history['stage'], 'complete')

    def test_globals_errors_stop_before_database_restore_and_record_failure(self):
        for failure in (1, 2, 3):
            with self.subTest(failure=failure):
                result, history, calls, reached = self.run_globals(failure)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(reached)
                self.assertEqual(history['result'], 'failed')
                self.assertEqual(history['stage'], 'restore-globals')
                self.assertEqual(history['detail'], 'globals restore failed')
                self.assertNotIn('SYNTHETIC_PRIVATE_SQL', result.stdout + result.stderr + json.dumps(history))

    def test_cleanup_failure_cannot_report_restore_success(self):
        for remaining, list_failure in [('synthetic-container', 0), ('', 42)]:
            result, history, _, _ = self.run_globals(cleanup_failure=42, remaining=remaining, list_failure=list_failure)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(history['result'], 'failed')
            self.assertEqual(history['stage'], 'cleanup')
            self.assertEqual(history['detail'], 'container cleanup failed')

    def test_already_missing_container_is_successful_cleanup(self):
        result, history, _, _ = self.run_globals(cleanup_failure=1)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(history['result'], 'success')

    def test_cleanup_removes_only_own_container_and_anonymous_volume(self):
        source = SCRIPT.read_text()
        cleanup = source.split('finish() {', 1)[1].split('local json', 1)[0]
        self.assertIn('docker rm -fv "$NAME"', cleanup)
        self.assertNotIn('prune', cleanup)
        self.assertNotIn('docker volume rm', cleanup)

    def test_restore_preserves_database_owner_and_privileges(self):
        remaining = SCRIPT.read_text().split('mapfile -t ROWS', 1)[1]
        self.assertIn('pg_restore -U "$RESTORE_USER" -d template1', remaining)
        self.assertIn('--create --clean --if-exists --exit-on-error', remaining)
        self.assertNotIn('--no-owner', remaining)
        self.assertNotIn('--no-acl', remaining)
        self.assertNotIn('CREATE DATABASE', remaining)


if __name__ == '__main__':
    unittest.main()
