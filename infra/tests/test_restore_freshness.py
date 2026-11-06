"""복원 실행 누락 경보: 생성식과 실제 promtool 시험자료를 함께 유지."""
import importlib.util
import json
from pathlib import Path
import sys
import unittest

spec = importlib.util.spec_from_file_location('restore_generator', Path(__file__).resolve().parents[1] / 'observability/grafana/generate.py')
generator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(generator)
RULE = generator.RULES['ject-restore-freshness'][0]
EXPR = RULE['data'][0]['model']['expr']
NODE = 'up{job="node",host="prod-data"}'
METRIC = 'ject_restore_test_last_run_timestamp_seconds{job="node",host="prod-data"}'


def fixture():
    cases = []
    def case(name, node, metric, expected, interval='1m', at='3m', metric_name=METRIC):
        series = []
        if node is not None:
            series.append({'series': NODE, 'values': node})
        if metric is not None:
            series.append({'series': metric_name, 'values': metric})
        cases.append({'name': name, 'interval': interval, 'input_series': series,
                      'promql_expr_test': [{'expr': f'count(({EXPR}) > 0) or vector(0)',
                                           'eval_time': at, 'exp_samples': [{'labels': '{}', 'value': expected}]}]})
    case('최근 실행', '1x3', '100x3', 0)
    case('지표 없음', '1x3', None, 1)
    case('미실행 0', '1x3', '0x3', 1)
    case('미래 시각', '1x3', '1000x3', 1)
    case('정확히32일 허용', '1x33', '86400x33', 0, '1d', '33d')
    case('32일1초 초과', '1x33', '86399x33', 1, '1d', '33d')
    case('표본 오래됨', '1x4', '100x1', 1, '1m', '4m')
    case('VM down 중복 억제', '0x3', None, 0)
    case('VM 없음 중복 억제', None, None, 0)
    case('VM 표본 오래됨', '1', None, 0, '1m', '4m')
    case('다른 호스트 성공 무시', '1x3', '100x3', 1, metric_name=METRIC.replace('prod-data', 'dev'))
    return {'evaluation_interval': '1m', 'tests': cases}


class RestoreFreshnessTests(unittest.TestCase):
    def test_warning_hold_and_limit_are_explicit(self):
        self.assertEqual(RULE['for'], '5m')
        self.assertEqual(RULE['labels']['severity'], 'warning')
        self.assertIn('32 * 86400', EXPR)
        self.assertIn('정확한 월별 실행기한 감시는 아니며', RULE['annotations']['description'])

    def test_scope_and_fixture_coverage(self):
        self.assertIn('unless on(host)', EXPR)
        self.assertIn('timestamp(', EXPR)
        self.assertEqual(len(fixture()['tests']), 11)


if __name__ == '__main__':
    if '--promtool-fixture' in sys.argv:
        print(json.dumps(fixture()))
    else:
        unittest.main()
