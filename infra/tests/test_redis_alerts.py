"""stdout opt-in 계약 검사. PromQL 평가/Grafana 수신 E2E를 대체하지 않는다."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'observability/grafana/redis-alerts.py'


class RedisAlertTests(unittest.TestCase):
    def run_generator(self, *args, cwd=None):
        return subprocess.run([sys.executable, '-B', str(SCRIPT), *args],
                              capture_output=True, text=True, cwd=cwd)

    def document(self, *hosts):
        result = self.run_generator('--hosts', *hosts)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_explicit_nonempty_hosts_required(self):
        for args in ([], ['--hosts'], ['--hosts', ''], ['--hosts', 'dev', 'dev'],
                     ['--hosts', 'dev|.*'], ['--hosts', 'bad"host'], ['--hosts', 'a' * 64]):
            with self.subTest(args=args):
                result = self.run_generator(*args)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(result.stdout, '')

    def test_stdout_only_no_generated_files_and_no_existing_rewrite(self):
        generated = SCRIPT.parent / 'provisioning/alerting/rules.yaml'
        before = generated.read_bytes()
        with tempfile.TemporaryDirectory() as directory:
            result = self.run_generator('--hosts', 'synthetic', cwd=directory)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(list(Path(directory).iterdir()), [])
        self.assertEqual(generated.read_bytes(), before)

    def test_plain_python_invocation_does_not_write_bytecode(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ('redis-alerts.py', 'generate.py'):
                (root / name).write_bytes((SCRIPT.parent / name).read_bytes())
            result = subprocess.run([sys.executable, str(root / SCRIPT.name), '--hosts', 'dev'],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(sorted(p.name for p in root.iterdir()), ['generate.py', 'redis-alerts.py'])

    def test_four_separate_rules_with_existing_grafana_contract(self):
        doc = self.document('prod-data', 'dev')
        self.assertEqual(doc['apiVersion'], 1)
        group, = doc['groups']
        self.assertEqual(group['interval'], '1m')
        self.assertEqual(len(group['rules']), 4)
        self.assertEqual(len({r['uid'] for r in group['rules']}), 4)
        for rule in group['rules']:
            self.assertEqual(rule['condition'], 'C')
            self.assertEqual(rule['noDataState'], 'OK')
            self.assertEqual(rule['execErrState'], 'Alerting')
            self.assertEqual(rule['data'][0]['datasourceUid'], 'prom')
            self.assertIn('job="integrations/redis",host=~"dev|prod-data"', rule['data'][0]['model']['expr'])
            self.assertIn('초안', rule['annotations']['description'])

    def test_memory_ratio_excludes_zero_limit_and_uses_strict_80_percent(self):
        rule = self.document('dev')['groups'][0]['rules'][0]
        expr = rule['data'][0]['model']['expr']
        self.assertIn(' / redis_memory_max_bytes', expr)
        self.assertIn(' > 0)', expr)
        self.assertEqual(rule['for'], '5m')
        self.assertEqual(rule['data'][1]['model']['conditions'][0]['evaluator'],
                         {'type': 'gt', 'params': [0.8]})

    def test_missing_is_per_expected_host_and_checks_both_timestamps(self):
        rule = self.document('dev', 'prod-data')['groups'][0]['rules'][2]
        expr = rule['data'][0]['model']['expr']
        for host in ('dev', 'prod-data'):
            self.assertIn(f'"host", "{host}"', expr)
        self.assertIn('unless on(host)', expr)
        self.assertEqual(expr.count('timestamp('), 2)
        self.assertEqual(expr.count('< 120'), 2)
        self.assertIn(' >= 0)', expr)  # redis_up=0 belongs to connection-failure, not absence.
        self.assertNotIn('last_over_time', expr)

    def test_promtool_fixtures_follow_current_generator_expressions(self):
        fixture = json.loads((SCRIPT.parents[2] / 'tests/redis-alerts-promql-test.json').read_text())
        rules = self.document('dev')['groups'][0]['rules']
        expected = []
        for rule in rules:
            expr = rule['data'][0]['model']['expr']
            evaluator = rule['data'][1]['model']['conditions'][0]['evaluator']
            op = {'gt': '>', 'lt': '<'}[evaluator['type']]
            value = evaluator['params'][0]
            expected.append(f'count(({expr}) {op} {value}) or vector(0)')
        self.assertEqual(len(fixture['tests']), 11)
        for case in fixture['tests']:
            self.assertEqual([x['expr'] for x in case['promql_expr_test']], expected)

    def test_zero_limit_is_separate_not_division_result(self):
        rule = self.document('dev')['groups'][0]['rules'][3]
        self.assertTrue(rule['data'][0]['model']['expr'].endswith(' == 0'))
        self.assertNotIn(' / ', rule['data'][0]['model']['expr'])


if __name__ == '__main__':
    unittest.main()
