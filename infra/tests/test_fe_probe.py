import importlib.util
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'observability/grafana'))
spec = importlib.util.spec_from_file_location('fe_alerts', ROOT / 'observability/grafana/fe-alerts.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
RULE = module.provisioning()['groups'][0]['rules'][0]
EXPR = RULE['data'][0]['model']['expr']


def fixture():
    series = 'probe_success{host="dev",job="integrations/blackbox/dev-fe",target="dev-fe"}'
    cases = [('healthy', [{'series': series, 'values': '1x6'}], 1),
             ('failed', [{'series': series, 'values': '0x6'}], 0),
             ('missing', [], 0),
             ('stale', [{'series': series, 'values': '1 _ _ _ _'}], 0),
             ('backend_not_frontend', [{'series': series.replace('dev-fe', 'dev'), 'values': '1x6'}], 0)]
    return {'evaluation_interval': '1m', 'tests': [
        {'name': name, 'interval': '1m', 'input_series': items,
         'promql_expr_test': [{'expr': EXPR, 'eval_time': '4m',
                              'exp_samples': [{'labels': '{target="dev-fe"}', 'value': value}]}]}
        for name, items, value in cases]}


class FEProbeTests(unittest.TestCase):
    def test_probe_is_opt_in_and_checks_body(self):
        path = ROOT / 'observability/alloy/fe.alloy.example'
        value = path.read_text()
        self.assertIn('fail_if_body_not_matches_regexp', value)
        self.assertIn('^ok[[:space:]]*$', value)
        self.assertIn('PROBE_DEV_FE_URL', value)
        self.assertFalse(path.with_suffix('').exists())

    def test_frontend_fails_independently_of_backend(self):
        self.assertEqual(RULE['for'], '3m')
        self.assertEqual(RULE['data'][1]['model']['conditions'][0]['evaluator'], {'type': 'lt', 'params': [1]})
        self.assertEqual(len(fixture()['tests']), 5)
        self.assertIn('timestamp', EXPR)


if __name__ == '__main__':
    if '--promtool-fixture' in sys.argv:
        print(json.dumps(fixture()))
    else:
        unittest.main()
