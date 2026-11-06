"""추가 이메일의 로컬 HCL 식만 평가. OCI/provider/state/tfvars 접근 없음."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1] / 'oci'


def block(text, marker):
    start = text.index(marker)
    opening = text.index('{', start)
    depth = 0
    for index in range(opening, len(text)):
        if text[index] == '{':
            depth += 1
        elif text[index] == '}':
            depth -= 1
            if depth == 0:
                return text[start:index + 1]
    raise AssertionError('unclosed HCL block')


class AlertSubscriptionTests(unittest.TestCase):
    def test_existing_subscription_unchanged_and_additional_sensitive(self):
        monitoring, variables = (ROOT / 'monitoring.tf').read_text(), (ROOT / 'variables.tf').read_text()
        old = block(monitoring, 'resource "oci_ons_subscription" "alert_email"')
        self.assertIn('endpoint       = var.alert_email', old)
        self.assertNotIn('for_each', old)
        additional = block(monitoring, 'resource "oci_ons_subscription" "additional_alert_email"')
        self.assertIn('nonsensitive(toset(keys(local.additional_alert_email_endpoints)))', additional)
        self.assertIn('endpoint       = local.additional_alert_email_endpoints[each.key]', additional)
        variable = block(variables, 'variable "additional_alert_emails"')
        self.assertIn('default     = []', variable)
        self.assertIn('sensitive   = true', variable)
        self.assertIn('nullable    = false', variable)
        self.assertNotIn('@gmail.com', monitoring + variables)

    @unittest.skipUnless(shutil.which('terraform'), 'Terraform CLI 없음; 설치하지 않음')
    def test_actual_hcl_normalization_default_and_stable_hash_keys(self):
        variables = (ROOT / 'variables.tf').read_text()
        monitoring = (ROOT / 'monitoring.tf').read_text()
        configuration = '\n'.join([block(variables, 'variable "alert_email"'),
                                    block(variables, 'variable "additional_alert_emails"'),
                                    block(monitoring, 'locals {')])
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / 'main.tf').write_text(configuration)
            for extra, expected in ((None, []), ([], []),
                                    ([' ', ' PERSONAL@example.test ', 'TEAM@example.test', 'team@example.test'], ['team@example.test'])):
                env = {'PATH': os.environ['PATH'], 'HOME': os.environ['HOME'],
                       'TF_IN_AUTOMATION': '1', 'CHECKPOINT_DISABLE': '1',
                       'TF_VAR_alert_email': 'personal@example.test'}
                if extra is not None:
                    env['TF_VAR_additional_alert_emails'] = json.dumps(extra)
                result = subprocess.run(['terraform', f'-chdir={tmp}', 'console', '-no-color'],
                                        input='jsonencode(nonsensitive(local.additional_alert_email_endpoints))\n',
                                        env=env, capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                values = json.loads(json.loads(result.stdout.strip()))
                self.assertEqual(sorted(values.values()), expected)
                for key in values:
                    self.assertRegex(key, r'^[a-f0-9]{64}$')


if __name__ == '__main__':
    unittest.main()
