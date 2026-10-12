from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from saba import daily
from saba.daily import DailyConfig, DailyError, load_config, register_command, run_daily

NOW = datetime(2026, 10, 12, 8, 3, tzinfo=timezone.utc)
CONFIG = DailyConfig(time="08:00", random_delay_minutes=5, weekdays=("MON", "TUE", "WED", "THU", "FRI"),
                     max_analysis_calls=20, max_insight_calls=20, send=True)


class DailyTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.dir = Path(temp.name)
        self.calls = []

    def steps(self, fail_at=None):
        def collect():
            self.calls.append("collect")
            if fail_at == "collect":
                raise DailyError("RSS 수집 실패 (종료 코드 1)")

        def build(now, config):
            self.calls.append(("build", config.max_analysis_calls, config.max_insight_calls))
            if fail_at == "build":
                raise RuntimeError("FAKE-SECRET-in-exception")
            return b"EML", "표시 19건"

        def deliver(eml):
            self.calls.append("send")
            return "발송 완료 1회"
        return dict(collect=collect, build=build, deliver=deliver)

    def run_with(self, config=CONFIG, fail_at=None):
        with self.assertLogs(level="INFO") as logs:
            code = run_daily(NOW, config, output_dir=self.dir, **self.steps(fail_at))
        return code, "\n".join(logs.output)

    def test_steps_in_order_with_daily_caps_and_send(self):
        code, log = self.run_with()
        self.assertEqual(code, 0)
        self.assertEqual(self.calls, ["collect", ("build", 20, 20), "send"])
        self.assertEqual((self.dir / f"daily_{NOW.astimezone():%Y%m%d}.eml").read_bytes(), b"EML")
        self.assertIn("발송 완료 1회", log)

    def test_missing_output_folder_created(self):  # 새 PC·실행 파일 묶음 (D-069)
        self.dir = self.dir / "output"
        code, _ = self.run_with()
        self.assertEqual(code, 0)
        self.assertTrue((self.dir / f"daily_{NOW.astimezone():%Y%m%d}.eml").exists())

    def test_failure_stops_before_send_without_retry_or_secret(self):
        for fail_at, expected in (("collect", ["collect"]), ("build", ["collect", ("build", 20, 20)])):
            with self.subTest(fail_at=fail_at):
                self.calls = []
                code, log = self.run_with(fail_at=fail_at)
                self.assertEqual(code, 1)
                self.assertEqual(self.calls, expected)  # 발송 없음, 재시도 없음
                self.assertIn("오늘은 발송하지 않음", log)
                self.assertNotIn("FAKE-SECRET", log)  # 예상 밖 오류는 종류 이름만

    def test_send_false_generates_only(self):
        code, _ = self.run_with(config=DailyConfig(**{**CONFIG.__dict__, "send": False}))
        self.assertEqual((code, self.calls[-1]), (0, ("build", 20, 20)))

    def test_config_file_validation(self):
        path = self.dir / "daily.json"
        base = {"time": "08:00", "random_delay_minutes": 5, "weekdays": ["MON"], "max_analysis_calls": 20,
                "max_insight_calls": 20, "send": True}
        path.write_text(json.dumps(base), encoding="utf-8")
        self.assertEqual(load_config(path).time, "08:00")
        for bad in ({"time": "8:00"}, {"time": "24:00"}, {"weekdays": ["XYZ"]}, {"weekdays": []},
                    {"max_analysis_calls": 99}, {"random_delay_minutes": -1}):
            with self.subTest(bad=bad):
                path.write_text(json.dumps(base | bad), encoding="utf-8")
                with self.assertRaises(DailyError):
                    load_config(path)
        self.assertEqual(load_config().max_analysis_calls, 20)  # 저장소 기본 설정 (D-061)

    def test_register_command_uses_config_and_does_not_run(self):
        command = register_command(CONFIG)
        for part in ("-Weekly", "Monday,Tuesday,Wednesday,Thursday,Friday", "-At 08:00",
                     "New-TimeSpan -Minutes 5", "-m saba.daily --run", daily.TASK_NAME):
            self.assertIn(part, command)
        later = register_command(DailyConfig(**{**CONFIG.__dict__, "time": "07:30", "weekdays": ("MON",)}))
        self.assertIn("-At 07:30", later)
        with patch("subprocess.run") as run, patch("sys.argv", ["daily", "--register"]), patch("builtins.print"):
            self.assertEqual(daily.main(), 0)
        run.assert_not_called()  # --apply 없이는 등록하지 않는다


if __name__ == "__main__":
    unittest.main()
