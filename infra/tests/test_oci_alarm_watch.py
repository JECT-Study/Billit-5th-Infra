"""ject-oci-alarm-watch: 알람 상태 변화에서 무엇을 알릴지만 확인(OCI·Discord 호출 없음)."""
import importlib.machinery
import importlib.util
from pathlib import Path
import unittest

PATH = Path(__file__).resolve().parents[1] / 'scripts/ject-oci-alarm-watch'
loader = importlib.machinery.SourceFileLoader('oci_alarm_watch', str(PATH))
spec = importlib.util.spec_from_loader('oci_alarm_watch', loader)
watch = importlib.util.module_from_spec(spec)
loader.exec_module(watch)


class OciAlarmWatchTests(unittest.TestCase):
    def test_new_firing_alarm_is_reported_once(self):
        self.assertEqual(watch.changes([], {'a': 'FIRING', 'b': 'OK'}), (['a'], [], ['a']))
        self.assertEqual(watch.changes(['a'], {'a': 'FIRING', 'b': 'OK'}), ([], [], ['a']))

    def test_resolved_only_when_reported_ok(self):
        self.assertEqual(watch.changes(['a'], {'a': 'OK'}), ([], ['a'], []))
        # 조회 결과에서 빠진 알람은 해소로 알리지 않고 계속 울리는 것으로 둔다.
        self.assertEqual(watch.changes(['a'], {'b': 'OK'}), ([], [], ['a']))

    def test_message_marks_resolved_and_severity(self):
        text = watch.message(['x'], ['y'], {'x': 'CRITICAL'})
        self.assertIn('**OCI 알람: x** (CRITICAL)', text)
        self.assertIn('**OCI 알람: y** (해소)', text)


if __name__ == '__main__':
    unittest.main()
