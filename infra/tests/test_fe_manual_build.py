"""FE 수동 빌드 계약의 합성 검증. Docker/Registry/Actions 실호출 없음."""
import copy
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import textwrap
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / 'github-workflows/build-fe-manual.yml'
SPEC = importlib.util.spec_from_file_location('verify_fe', ROOT / 'scripts/verify-fe-image.py')
M = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)
SOURCE, INFRA = 'a' * 40, 'b' * 40
IMAGE = 'ghcr.io/ject-study/ject-fe:synthetic'
INFO = {'Id': 'sha256:' + 'c' * 64, 'Os': 'linux', 'Architecture': 'arm64',
        'Config': {'User': 'node', 'Healthcheck': {'Test': ['CMD-SHELL', 'wget']}, 'Labels': {
            'org.opencontainers.image.source': M.INFRA_SOURCE, 'io.ject.app.source': M.SOURCE,
            'org.opencontainers.image.revision': SOURCE, 'io.ject.infra.revision': INFRA}}}


def shell_step(name):
    block = WORKFLOW.read_text().split('      - name: ' + name + '\n', 1)[1].split('\n      - name:', 1)[0]
    return textwrap.dedent(block.split('        run: |\n', 1)[1])


class FEManualBuildTests(unittest.TestCase):
    def verify(self, info=None, uid='1000', state=None, probe='fe-probes-ok', remaining='', failure=None):
        calls = []
        def docker(*args, **kwargs):
            calls.append(args)
            if failure and args[0] == failure:
                raise RuntimeError('synthetic operation failed')
            if args[:2] == ('image','inspect'):
                output = json.dumps([info if info is not None else INFO])
            elif args[0] == 'inspect':
                output = json.dumps(state or {'Running': True, 'OOMKilled': False, 'Health': {'Status':'healthy'}})
            elif args[0] == 'exec':
                output = uid if args[2] == 'id' else probe
            elif args[0] == 'container': output = remaining
            else: output = ''
            return SimpleNamespace(returncode=0,stdout=output)
        with patch.object(M,'docker',side_effect=docker), patch.object(M.time,'sleep'):
            try: return M.verify(IMAGE,SOURCE,INFRA),calls,None
            except (ValueError,RuntimeError) as error: return None,calls,str(error)

    def test_success_is_isolated_and_preserves_distinct_revisions(self):
        result,calls,error=self.verify()
        self.assertIsNone(error)
        self.assertEqual(result['source_sha'],SOURCE)
        self.assertEqual(result['infra_sha'],INFRA)
        run=next(args for args in calls if args[0]=='run')
        self.assertEqual(run[run.index('--network')+1],'none')
        self.assertEqual(run[run.index('--memory')+1],'384m')
        self.assertEqual(run[run.index('--memory-swap')+1],'384m')
        self.assertNotIn('-p',run)
        self.assertIn('--pull=never',run)
        self.assertEqual(sum(args[0]=='rm' for args in calls),1)
        self.assertIn('business_e2e',result['not_verified'])

    def test_wrong_architecture_and_provenance_fail_before_running(self):
        invalid=[]
        bad=copy.deepcopy(INFO);bad['Architecture']='amd64';invalid.append(bad)
        for key in INFO['Config']['Labels']:
            bad=copy.deepcopy(INFO);bad['Config']['Labels'][key]='wrong';invalid.append(bad)
        for info in invalid:
            result,calls,error=self.verify(info=info)
            self.assertIsNone(result)
            self.assertIsNotNone(error)
            self.assertFalse(any(args[0]=='run' for args in calls))

    def test_failed_health_root_or_nonroot_checks_cleanup_and_fail(self):
        for options in ({'uid':'0'},{'probe':'wrong root'},
                        {'state':{'Running':False}},
                        {'state':{'Running':True,'OOMKilled':True}},
                        {'state':{'Running':True,'Health':{'Status':'unhealthy'}}},
                        {'failure':'run'}):
            with self.subTest(options=options):
                result,calls,error=self.verify(**options)
                self.assertIsNone(result)
                self.assertIsNotNone(error)
                self.assertTrue(any(args[0]=='rm' for args in calls))
                self.assertTrue(any(args[0]=='container' for args in calls))

    def test_cleanup_failure_cannot_report_success(self):
        result,_,error=self.verify(remaining='owned-container')
        self.assertIsNone(result)
        self.assertIn('cleanup failed',error)

    def test_input_validation_has_fixed_owner_namespace_and_rejects_injection(self):
        script=shell_step('Validate source and image namespace')
        with tempfile.TemporaryDirectory() as tmp:
            output=Path(tmp)/'output'
            env={**os.environ,'SOURCE_SHA':SOURCE,'INFRA_SHA':INFRA,'REPOSITORY_OWNER':'JECT-Study',
                 'GITHUB_RUN_ID':'12','GITHUB_RUN_ATTEMPT':'1','GITHUB_OUTPUT':str(output)}
            result=subprocess.run(['bash','-c',script],env=env,capture_output=True)
            self.assertEqual(result.returncode,0)
            self.assertIn('repository=ghcr.io/ject-study/ject-fe',output.read_text())
            for invalid in ('develop','a'*39,'$(touch injected)', 'a'*40+'\nwrong'):
                output.unlink(missing_ok=True)
                result=subprocess.run(['bash','-c',script],env={**env,'SOURCE_SHA':invalid},capture_output=True)
                self.assertNotEqual(result.returncode,0)
                self.assertFalse(output.exists())

    def test_workflow_only_publishes_after_probes_without_app_status_or_deploy(self):
        value=WORKFLOW.read_text()
        self.assertEqual(value.count('persist-credentials: false'),2)
        self.assertIn('repository: JECT-Study/Billit-5th-Client',value)
        self.assertIn('ref: ${{ inputs.source_sha }}',value)
        self.assertLess(value.index('- name: Verify isolated FE image'),value.index('docker login'))
        self.assertLess(value.index('- name: Verify isolated FE image'),value.index('docker push'))
        self.assertNotIn('always()',value)
        self.assertNotIn('statuses: write',value)
        self.assertNotIn('ject/dev-verified',value)
        self.assertNotIn('ject-deploy',value)
        self.assertNotIn('NEXT_PUBLIC_API_URL=',value)
        self.assertIn('workflow_dispatch:',value)
        self.assertNotIn('workflow_call:',value)
        self.assertIn("github.event.repository.private == false",value)

    def test_workflow_run_blocks_have_valid_shell(self):
        for name in ('Validate source and image namespace','Verify checkout revisions',
                     'Build source Dockerfile locally','Verify isolated FE image before publishing',
                     'Publish verified local image and report digest'):
            with self.subTest(step=name):
                result=subprocess.run(['bash','-n'],input=shell_step(name),capture_output=True,text=True)
                self.assertEqual(result.returncode,0,result.stderr)

    def test_publish_shell_validates_digest_and_removes_temporary_credentials(self):
        script = shell_step('Publish verified local image and report digest')
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fake = root / 'docker'
            fake.write_text('#!/bin/sh\ncase "$1" in\nlogin) cat >/dev/null;;\npush) exit "${PUSH_EXIT:-0}";;\nimage) printf "%s\\n" "$PUBLISHED";;\n*) exit 1;;\nesac\n')
            fake.chmod(0o700)
            digest = 'ghcr.io/ject-study/ject-fe@sha256:' + 'd' * 64
            env = {**os.environ, 'PATH': str(root) + os.pathsep + os.environ['PATH'],
                   'RUNNER_TEMP': tmp, 'IMAGE': IMAGE, 'IMAGE_REPOSITORY': 'ghcr.io/ject-study/ject-fe',
                   'GHCR_TOKEN': 'synthetic', 'GITHUB_ACTOR': 'synthetic', 'SOURCE_SHA': SOURCE,
                   'INFRA_SHA': INFRA, 'GITHUB_OUTPUT': str(root / 'output'),
                   'GITHUB_STEP_SUMMARY': str(root / 'summary')}
            for published, push_exit, success in ((digest, '0', True),
                                                   ('ghcr.io/other/ject-fe@sha256:' + 'd' * 64, '0', False),
                                                   (digest, '1', False)):
                for name in ('output', 'summary'):
                    (root / name).unlink(missing_ok=True)
                result = subprocess.run(['bash', '-c', script],
                                        env={**env, 'PUBLISHED': published, 'PUSH_EXIT': push_exit},
                                        capture_output=True, text=True)
                self.assertEqual(result.returncode == 0, success, result.stderr)
                self.assertEqual(list(root.glob('fe-registry.*')), [])
                self.assertEqual((root / 'summary').exists(), success)
                if success:
                    self.assertIn('image=' + digest, (root / 'output').read_text())
                    self.assertNotIn('synthetic', (root / 'summary').read_text())


if __name__ == '__main__':
    unittest.main()
