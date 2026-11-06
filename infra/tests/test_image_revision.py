"""Run the workflow's real revision shell with a local Docker double; no network."""
import os
from pathlib import Path
import subprocess
import tempfile
import textwrap
import unittest

WORKFLOW = Path(__file__).resolve().parents[1] / 'github-workflows/deploy-via-bastion.yml'


class ImageRevisionTests(unittest.TestCase):
    def run_check(self, revision='a' * 40, commit='a' * 40, fail=''):
        workflow = WORKFLOW.read_text()
        step = workflow.split('      - name: Verify image revision\n', 1)[1].split('\n      - name:', 1)[0]
        script = textwrap.dedent(step.split('        run: |\n', 1)[1])
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            docker = root / 'docker'
            docker.write_text('''#!/bin/sh
printf '%s\\n' "$*" >> "$CALLS"
case "$1" in
 login) cat >/dev/null; [ "$FAIL" != login ] ;;
 pull) [ "$FAIL" != pull ] ;;
 image) [ "$FAIL" != inspect ] || exit 1; printf '%s\\n' "$REVISION" ;;
 *) exit 9 ;;
esac
''')
            docker.chmod(0o700)
            output = root / 'output'
            env = {**os.environ, 'PATH': directory + ':' + os.environ['PATH'],
                   'RUNNER_TEMP': directory, 'GITHUB_OUTPUT': str(output),
                   'GITHUB_SHA': 'a' * 40, 'GITHUB_ACTOR': 'test', 'COMMIT': commit,
                   'GHCR_TOKEN': 'synthetic', 'REVISION': revision, 'FAIL': fail,
                   'CALLS': str(root / 'calls'),
                   'IMAGE': 'ghcr.io/test/ject-app@sha256:' + 'b' * 64}
            result = subprocess.run(['bash', '-c', script], env=env, capture_output=True, text=True)
            evidence = output.read_text() if output.exists() else ''
            self.assertEqual(list(root.glob('revision-docker.*')), [])
            return result.returncode, evidence

    def test_matching_revision(self):
        self.assertEqual(self.run_check(), (0, 'sha=' + 'a' * 40 + '\n'))

    def test_default_commit_is_checked(self):
        self.assertEqual(self.run_check(commit=''), (0, 'sha=' + 'a' * 40 + '\n'))

    def test_mismatch_missing_and_invalid_commit_fail_closed(self):
        for args in ({'revision': 'c' * 40}, {'revision': ''}, {'revision': '<no value>'},
                     {'commit': 'invalid'}, {'commit': '$(touch /tmp/not-executed)'}):
            with self.subTest(args=args):
                code, evidence = self.run_check(**args)
                self.assertNotEqual(code, 0)
                self.assertEqual(evidence, '')

    def test_registry_failures_do_not_produce_verified_sha(self):
        for failure in ('login', 'pull', 'inspect'):
            with self.subTest(failure=failure):
                code, evidence = self.run_check(fail=failure)
                self.assertNotEqual(code, 0)
                self.assertEqual(evidence, '')

    def test_verification_precedes_remote_work_and_mark_uses_verified_sha(self):
        workflow = WORKFLOW.read_text()
        self.assertLess(workflow.index('- name: Verify image revision'), workflow.index('- name: Create bastion session'))
        mark = workflow.split('- name: Mark digest as verified in dev', 1)[1].split('- name:', 1)[0]
        self.assertIn('SHA: ${{ steps.revision.outputs.sha }}', mark)
        step = workflow.split('- name: Verify image revision', 1)[1].split('- name:', 1)[0]
        self.assertIn("if: inputs.action == 'deploy'", step)


if __name__ == '__main__':
    unittest.main()
