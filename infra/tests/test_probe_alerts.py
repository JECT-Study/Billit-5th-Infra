"""로컬 구조검증과 promtool stdin fixture 생성. unittest는 네트워크 호출 없음."""
import importlib.util
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('probe_rules_generator', ROOT / 'observability/grafana/generate.py')
generator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(generator)
RULE = next(r for r in generator.RULES['ject-external'] if r['uid'] == 'ject-probe-fail')
EXPR = RULE['data'][0]['model']['expr']


def fixture():
    data = json.loads((Path(__file__).parent / 'probe-alerts.promtool.json').read_text())
    for case in data['tests']:
        for check in case['promql_expr_test']:
            check['expr'] = EXPR
    return data


class ProbeAlertTests(unittest.TestCase):
    def test_existing_threshold_and_hold_are_preserved(self):
        self.assertEqual(RULE['for'], '3m')
        evaluator = RULE['data'][1]['model']['conditions'][0]['evaluator']
        self.assertEqual(evaluator, {'type': 'lt', 'params': [1]})
        self.assertIn('$labels.target', RULE['annotations']['summary'])

    def test_scope_matches_observed_blackbox_jobs(self):
        self.assertIn('job=~"integrations/blackbox/(dev|prod)"', EXPR)
        self.assertIn('host="dev"', EXPR)
        self.assertNotIn('job="probe"', EXPR)
        cases = fixture()['tests']
        self.assertTrue(any('job="probe"' in item['series'] for case in cases for item in case.get('input_series', [])))

    def test_app_collection_success_is_not_business_health(self):
        dashboard = generator.app().json()
        self.assertIn('수집 성공은 업무 정상 판정이 아닙니다', dashboard['description'])
        self.assertIn('No data', dashboard['description'])
        panel = next(p for p in dashboard['panels'] if p['title'] == '앱 지표 수집')
        self.assertEqual(panel['fieldConfig']['defaults']['mappings'][0]['options']['1']['text'], '수집 성공')
        self.assertNotIn('description', generator.overview().json())
        self.assertNotIn('description', generator.logs().json())

    def test_fixture_covers_missing_stale_and_outside(self):
        data = fixture()
        self.assertEqual(len(data['tests']), 9)
        self.assertNotIn('__PROBE_EXPR__', json.dumps(data))
        self.assertTrue(all(c['exp_samples'] for t in data['tests'] for c in t['promql_expr_test']))


if __name__ == '__main__':
    if '--promtool-fixture' in sys.argv:
        print(json.dumps(fixture()))
    else:
        unittest.main()
