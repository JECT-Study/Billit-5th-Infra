import importlib.util
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('meta_generator', ROOT / 'observability/grafana/generate.py')
generator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(generator)


def rules():
    return {r['uid']: r for r in generator.RULES['ject-observability']}


def fixture():
    data = json.loads(Path(__file__).with_name('meta-alerts.promtool.json').read_text())
    for test in data['tests']:
        for check in test['promql_expr_test']:
            uid = check['expr']
            expr = rules()[uid]['data'][0]['model']['expr']
            check['expr'] = f'count(({expr}) > 0) or vector(0)'
    return data


class MetaTests(unittest.TestCase):
    def test_three_rules_have_hold_and_initial_value_warning(self):
        self.assertEqual(len(rules()), 3)
        for r in rules().values():
            self.assertEqual(r['for'], '2m')
            self.assertIn('초기값', r['annotations']['description'])
            self.assertEqual(r['data'][1]['model']['conditions'][0]['evaluator'], {'type': 'gt', 'params': [0]})

    def test_scope_and_failure_boundary_are_explicit(self):
        component = rules()['ject-obs-component-down']
        expr = component['data'][0]['model']['expr']
        self.assertIn('timestamp(', expr)
        self.assertIn('< 180', expr)
        self.assertIn('host="dev"', expr)
        self.assertIn('OCI', component['annotations']['description'])
        for uid in ('ject-metrics-write-failed', 'ject-logs-write-dropped'):
            expr = rules()[uid]['data'][0]['model']['expr']
            self.assertIn('job="integrations/self"', expr)
            self.assertIn('host=~"dev|prod-app|prod-data"', expr)
            self.assertIn('increase(', expr)

    def test_fixture_is_bound_to_current_generator(self):
        self.assertGreaterEqual(len(fixture()['tests']), 12)
        self.assertTrue(all('count(' in c['expr'] for t in fixture()['tests'] for c in t['promql_expr_test']))


if __name__ == '__main__':
    if '--promtool-fixture' in sys.argv:
        print(json.dumps(fixture()))
    else:
        unittest.main()
