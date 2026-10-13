from datetime import date, datetime, timezone
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

        def deliver(eml, mail_file=""):
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
        self.assertEqual((self.dir / f"{NOW.astimezone():%y/%m}/daily_{NOW.astimezone():%Y%m%d_%H%M}.eml").read_bytes(), b"EML")
        self.assertIn("발송 완료 1회", log)

    def test_missing_output_folder_created(self):  # 새 PC·실행 파일 묶음 (D-069)
        self.dir = self.dir / "output"
        code, _ = self.run_with()
        self.assertEqual(code, 0)
        self.assertTrue((self.dir / f"{NOW.astimezone():%y/%m}/daily_{NOW.astimezone():%Y%m%d_%H%M}.eml").exists())

    def test_month_year_transition_and_relative_delivery(self):
        seen = []
        for now in (datetime(2026, 12, 31, 20, tzinfo=timezone.utc), datetime(2027, 1, 31, 20, tzinfo=timezone.utc)):
            with self.assertLogs(level="INFO") as logs:
                code = run_daily(now, CONFIG, output_dir=self.dir, collect=lambda: None,
                                 build=lambda now, config: (b"X", "표시 1건"),
                                 deliver=lambda data, name: seen.append(name) or "발송 완료")
            local = now.astimezone()
            expected = f"{local:%y/%m}/daily_{local:%Y%m%d_%H%M}.eml"
            self.assertEqual((code, seen[-1]), (0, expected))
            self.assertEqual((self.dir / expected).read_bytes(), b"X")
            self.assertIn(expected, '\n'.join(logs.output))

    def test_concurrent_monthly_saves_do_not_overwrite(self):
        from concurrent.futures import ThreadPoolExecutor
        def run(number):
            return run_daily(NOW, CONFIG, output_dir=self.dir, collect=lambda: None,
                             build=lambda now, config: (str(number).encode(), "표시 1건"),
                             deliver=lambda data, name: "발송 완료")
        with ThreadPoolExecutor(max_workers=4) as pool:
            self.assertEqual(list(pool.map(run, range(4))), [0] * 4)
        files = list(self.dir.rglob("*.eml"))
        self.assertEqual(len(files), 4)
        self.assertEqual({p.read_bytes() for p in files}, {str(i).encode() for i in range(4)})
        self.assertEqual({p.name.rsplit('.', 1)[0].rsplit('-', 1)[-1] for p in files if '-' in p.name}, {"2", "3", "4"})

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
                    {"max_analysis_calls": 99}, {"random_delay_minutes": -1}, {"random_delay_minutes": 31},
                    {"mode": "yearly"}, {"mode": "monthly", "month_days": []}, {"mode": "monthly", "month_days": [32]},
                    {"mode": "dates", "dates": []}, {"mode": "dates", "dates": ["2026-13-01"]}, {"log_days": 3},
                    {"mail_days": 0}):
            with self.subTest(bad=bad):
                path.write_text(json.dumps(base | bad), encoding="utf-8")
                with self.assertRaises(DailyError):
                    load_config(path)
        self.assertEqual(load_config().max_analysis_calls, 30)  # 저장소 기본 설정 (D-061, 2026-10-13 사용자 승인으로 30)
        path.write_text(json.dumps(base), encoding="utf-8")  # 예전 형식 (mode 등 없음) 은 기본값
        config = load_config(path)
        self.assertEqual((config.mode, config.log_days, config.mail_days), ("weekly", 90, 30))

    def test_save_round_trip(self):
        path = self.dir / "daily.json"
        config = DailyConfig(**{**CONFIG.__dict__, "mode": "dates", "dates": ("2026-10-20",), "mail_days": 45})
        daily.save_config(config, path)
        self.assertEqual(load_config(path), config)

    def test_register_command_uses_config_and_does_not_run(self):
        command = register_command(CONFIG)
        for part in ("-Daily", "-At 08:00",  # 매일 깨우고 날짜는 --run 이 판단 (D-072)
                     "New-TimeSpan -Minutes 5", "-m saba.daily --run", daily.TASK_NAME):
            self.assertIn(part, command)
        later = register_command(DailyConfig(**{**CONFIG.__dict__, "time": "07:30", "weekdays": ("MON",)}))
        self.assertIn("-At 07:30", later)
        with patch("subprocess.run") as run, patch("sys.argv", ["daily", "--register"]), patch("builtins.print"):
            self.assertEqual(daily.main(), 0)
        run.assert_not_called()  # --apply 없이는 등록하지 않는다


if __name__ == "__main__":
    unittest.main()

class RunOptionTests(unittest.TestCase):
    """수동 실행 옵션과 동시 실행 잠금 (D-071)."""

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.lock = Path(temp.name) / "daily.lock"
        patches = [patch.object(daily, "LOG_DIR", Path(temp.name)), patch.object(daily, "LOCK_PATH", self.lock),
                   patch.object(daily, "load_config", return_value=CONFIG), patch("logging.basicConfig"),
                   patch.object(daily, "scheduled_on", return_value=True),  # 요일과 관계없이 테스트
                   patch.object(daily, "ROOT", Path(temp.name))]  # 보관 정리가 저장소 파일을 건드리지 않게
        for item in patches:
            item.start()
            self.addCleanup(item.stop)

    def main(self, *args):
        with patch("sys.argv", ["daily", "--run", *args]), patch.object(daily, "run_daily", return_value=0) as run, \
                self.assertLogs(level="INFO") as logs:
            code = daily.main()
        return code, run, "\n".join(logs.output)

    def test_lock_allows_one_run_at_a_time(self):
        self.assertFalse(daily.is_running(self.lock))
        with daily.run_lock(self.lock):
            self.assertTrue(daily.is_running(self.lock))
            with self.assertRaises(DailyError):
                with daily.run_lock(self.lock):
                    pass
        self.assertFalse(daily.is_running(self.lock))  # 풀린 뒤 다시 실행 가능

    def test_manual_no_send_overrides_config(self):
        code, run, log = self.main("--manual", "--no-send")
        self.assertEqual(code, 0)
        self.assertFalse(run.call_args.args[1].send)
        self.assertIn("관리 페이지 수동 실행 (발송 없이)", log)
        code, run, log = self.main()
        self.assertTrue(run.call_args.args[1].send)
        self.assertIn("자동 실행 (발송 포함)", log)

    def test_second_run_skipped_while_running(self):
        with daily.run_lock(self.lock):
            code, run, log = self.main("--manual")
        self.assertEqual(code, 3)
        run.assert_not_called()  # 수집·호출·발송 없음
        self.assertIn("이미 실행 중", log)


class CollectTests(unittest.TestCase):
    def test_failure_names_failed_sources_only(self):  # D-074
        from types import SimpleNamespace
        out = SimpleNamespace(returncode=1, stdout="", stderr="ERROR: [boannews] 비공개 원문 내용\n"
                              "INFO: RSS Source 요약: 대상 6개 · 성공 5개 · 실패 1개 (boannews)\n")
        with patch("subprocess.run", return_value=out), self.assertRaises(DailyError) as caught:
            daily.collect_rss()
        self.assertEqual(str(caught.exception), "RSS 수집 실패 (종료 코드 1: boannews)")


class ScheduleTests(unittest.TestCase):
    """매일·매주·매월·특정 날짜 예약 (D-072)."""

    def config(self, **changes):
        return DailyConfig(**{**CONFIG.__dict__, **changes})

    def test_scheduled_on_each_mode(self):
        monday, saturday = date(2026, 10, 12), date(2026, 10, 17)
        self.assertTrue(daily.scheduled_on(self.config(), monday))
        self.assertFalse(daily.scheduled_on(self.config(), saturday))
        self.assertTrue(daily.scheduled_on(self.config(mode="daily"), saturday))
        self.assertTrue(daily.scheduled_on(self.config(mode="monthly", month_days=(17,)), saturday))
        self.assertFalse(daily.scheduled_on(self.config(mode="monthly", month_days=(17,)), monday))
        self.assertTrue(daily.scheduled_on(self.config(mode="dates", dates=("2026-10-17",)), saturday))
        self.assertFalse(daily.scheduled_on(self.config(mode="dates", dates=("2026-10-17",)), monday))

    def test_next_runs_skip_past_time_and_other_days(self):
        now = datetime(2026, 10, 12, 9, 0, tzinfo=timezone.utc)  # 월요일 09:00
        runs = daily.next_runs(self.config(), now, 3)
        self.assertEqual([r.strftime("%m-%d %H:%M") for r in runs], ["10-13 08:00", "10-14 08:00", "10-15 08:00"])
        once = daily.next_runs(self.config(mode="dates", dates=("2026-10-12", "2026-10-30"), time="15:00"), now, 5)
        self.assertEqual([r.strftime("%m-%d %H:%M") for r in once], ["10-12 15:00", "10-30 15:00"])

    def test_automatic_run_exits_quietly_on_other_days(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(daily, "LOG_DIR", Path(temp)),                 patch.object(daily, "load_config", return_value=self.config(mode="dates", dates=("2000-01-01",))),                 patch.object(daily, "run_daily") as run, patch("sys.argv", ["daily", "--run"]):
            self.assertEqual(daily.main(), 0)
            run.assert_not_called()
            self.assertEqual(list(Path(temp).iterdir()), [])  # 로그도 남기지 않음

