"""접속 기록 업로드 경보: 두 운영 서버를 보고, 지표가 없을 때도 울리는지 생성식으로 확인."""
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('alert_generator', Path(__file__).resolve().parents[1] / 'observability/grafana/generate.py')
generator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(generator)
RULE = generator.RULES['ject-access-log'][0]
EXPR = RULE['data'][0]['model']['expr']
SHIP = (Path(__file__).resolve().parents[1] / 'scripts/ject-access-log-ship').read_text()


class AccessLogAlertTests(unittest.TestCase):
    def test_threshold_and_severity(self):
        self.assertEqual(RULE['data'][1]['model']['conditions'][0]['evaluator'], {'type': 'gt', 'params': [26]})
        self.assertEqual(RULE['for'], '5m')
        self.assertEqual(RULE['labels']['severity'], 'warning')

    def test_missing_metric_alerts_only_on_live_prod_hosts(self):
        self.assertIn('host=~"prod-app|prod-data"', EXPR)
        self.assertIn('unless on(host) ject_access_log_ship_last_success_timestamp_seconds', EXPR)
        self.assertIn('999 *', EXPR)

    def test_script_writes_the_metric_the_rule_reads(self):
        self.assertIn('ject_access_log_ship_last_success_timestamp_seconds %s', SHIP)
        # 업로드가 실패하면(set -e) 지표를 쓰기 전에 끝나야 한다.
        self.assertLess(SHIP.index('os object put'), SHIP.index('ject_access_log.prom'))


if __name__ == '__main__':
    unittest.main()
