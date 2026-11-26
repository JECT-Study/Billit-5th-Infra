"""ject-obs-watch: 언제 알리고 언제 조용한지 상태 계산만 확인(네트워크 호출 없음)."""
from pathlib import Path
import subprocess
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/ject-obs-watch'


def step(fails, alerted, now, result):
    out = subprocess.run(['bash', '-c', f'source "{SCRIPT}" --source-only; next_state {fails} {alerted} {now} {result}'],
                         capture_output=True, text=True, timeout=5)
    assert out.returncode == 0, out.stderr
    return out.stdout.split()


class ObsWatchTests(unittest.TestCase):
    def test_short_outage_stays_quiet(self):
        self.assertEqual(step(0, 0, 1000, 'fail'), ['1', '0', 'none'])
        self.assertEqual(step(1, 0, 1120, 'fail'), ['2', '0', 'none'])
        self.assertEqual(step(2, 0, 1240, 'ok'), ['0', '0', 'none'])

    def test_third_failure_alerts_once(self):
        self.assertEqual(step(2, 0, 1240, 'fail'), ['3', '1240', 'firing'])
        self.assertEqual(step(3, 1240, 1360, 'fail'), ['4', '1240', 'none'])

    def test_repeats_after_four_hours(self):
        self.assertEqual(step(100, 1240, 1240 + 14399, 'fail'), ['101', '1240', 'none'])
        self.assertEqual(step(100, 1240, 1240 + 14400, 'fail'), ['101', '15640', 'firing'])

    def test_recovery_notifies_only_after_an_alert(self):
        self.assertEqual(step(5, 1240, 2000, 'ok'), ['0', '0', 'resolved'])
        self.assertEqual(step(2, 0, 2000, 'ok'), ['0', '0', 'none'])


if __name__ == '__main__':
    unittest.main()
