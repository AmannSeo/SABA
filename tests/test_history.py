from datetime import date
from pathlib import Path
import tempfile
import unittest

from saba.history import append_change, cleanup, load_runs, mail_name, mail_path, mail_paths, parse_runs, read_changes, read_log, storage_status

LOG = """2026-10-12 09:17:15,224 INFO RSS 수집 완료
2026-10-12 09:17:35,444 INFO 메일 생성 완료: daily_20261012.eml · 표시 3건 · 분석 재사용 0 · 신규 4 · 실패 0 · 시사점 재사용 0 · 신규 3 · 실패 0 · 1,346,272 bytes
2026-10-12 09:17:36,688 INFO 발송 완료 1회: 받는 사람 가상 1명 · 메시지 1,346,322 bytes · 포트 465
2026-10-12 14:26:55,911 INFO 실행 시작: 관리 페이지 수동 실행 (발송 포함)
2026-10-12 14:26:56,000 INFO 보관 기간 정리: 로그 1개, 메일 2개 삭제
2026-10-12 14:26:58,794 INFO RSS 수집 완료
2026-10-12 14:27:41,071 ERROR 분석·메일 생성 단계 실패: 메일 생성 실패 (표시할 기사 0건) · 오늘은 발송하지 않음
2026-10-12 15:00:01,000 INFO 실행 시작: 자동 실행 (발송 포함)
2026-10-12 15:00:01,500 WARNING 관리 페이지 수동 실행: 이미 실행 중입니다 · 이번 실행은 건너뜀
2026-10-12 15:00:03,000 INFO RSS 수집 완료
2026-10-12 15:00:40,000 INFO 메일 생성 완료: daily_20261012_1500.eml · 표시 7건 · 분석 재사용 1 · 신규 10 · 실패 0 · 시사점 재사용 1 · 신규 6 · 실패 0 · 112,961 bytes
2026-10-12 15:00:41,000 INFO 발송하지 않음 (send=false)
"""


class HistoryTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        (self.root / "logs").mkdir()
        (self.root / "output").mkdir()
        self.log = self.root / "logs" / "daily_20261012.log"
        self.log.write_text(LOG, encoding="utf-8")

    def test_runs_from_old_and_new_log_format(self):
        runs = parse_runs(read_log(self.log))
        self.assertEqual([r.result for r in runs], ["성공", "실패", "성공 (발송 안 함)", "건너뜀"])
        old, failed, nosend, skipped = runs
        self.assertEqual((old.origin, old.articles, old.ai_calls, old.sent), ("주체 미기록 (이전 형식)", 3, 7, True))
        self.assertEqual(failed.origin, "관리 페이지 수동 실행 (발송 포함)")
        self.assertEqual(failed.error, "분석·메일 생성 단계: 메일 생성 실패 (표시할 기사 0건)")
        self.assertIn(("보관 정리", "14:26", "완료", "로그 1개, 메일 2개 삭제"), failed.stages)
        self.assertEqual((nosend.mail_file, nosend.ai_calls, nosend.sent), ("daily_20261012_1500.eml", 16, False))
        self.assertEqual(skipped.error, "이미 실행 중이라 건너뜀")

    def test_summary_with_dropped_count_still_parsed(self):
        self.log.write_text("2026-10-12 16:00:01,000 INFO 실행 시작: 자동 실행 (발송 없이)\n"
                            "2026-10-12 16:00:40,000 INFO 메일 생성 완료: daily_20261012_1600.eml · 표시 5건 · 분석 재사용 2 · 신규 3"
                            " · 실패 0 · 분석 없음 제외 4 · 시사점 재사용 0 · 신규 1 · 실패 0 · 99,000 bytes\n", encoding="utf-8")
        [run] = parse_runs(read_log(self.log))
        self.assertEqual((run.mail_file, run.articles, run.ai_calls), ("daily_20261012_1600.eml", 5, 4))

    def test_summary_with_all_exclusion_reasons_still_parsed(self):
        text = ('2026-10-12 16:00:01,000 INFO 실행 시작: 자동 실행 (발송 없이)\n'
                '2026-10-12 16:00:40,000 INFO 메일 생성 완료: 26/10/daily_20261012_1600.eml · 표시 5건'
                ' · 분석 재사용 2 · 신규 3 · 실패 1 · 분석 없음 제외 15'
                ' · 게재 제외 입력 부족 7 · 응답 오류 3 · 상한 2 · 대상 밖 2 · 기타 1'
                ' · 시사점 재사용 0 · 신규 1 · 실패 0 · 99,000 bytes\n')
        self.log.write_text(text, encoding='utf-8')
        [run] = parse_runs(read_log(self.log))
        self.assertEqual((run.mail_file, run.articles, run.ai_calls), ('26/10/daily_20261012_1600.eml', 5, 4))

    def test_legacy_top_level_name_finds_moved_monthly_file(self):
        output = self.root / "output"
        (output / "26" / "10").mkdir(parents=True)
        moved = output / "26" / "10" / "daily_20261013_0845.eml"
        moved.write_bytes(b"x")
        self.assertEqual(mail_path(output, "daily_20261013_0845.eml"), moved)  # 로그의 예전 이름 (F7 정리)
        self.assertEqual(mail_name(output, "daily_20261013_0845.eml"), "26/10/daily_20261013_0845.eml")
        (output / "daily_20261013_0845.eml").write_bytes(b"y")
        self.assertEqual(mail_path(output, "daily_20261013_0845.eml"), output / "daily_20261013_0845.eml")  # 최상위가 있으면 최상위
        self.assertEqual(mail_path(output, "daily_20261014_0900.eml"), output / "daily_20261014_0900.eml")  # 어디에도 없으면 그대로
        self.assertEqual(mail_name(output, "../x.eml"), "../x.eml")  # 허용되지 않는 이름은 바꾸지 않는다

    def test_load_runs_newest_first(self):
        starts = [r.start for r in load_runs(self.root / "logs")]
        self.assertEqual(starts, sorted(starts, reverse=True))

    def test_monthly_paths_cleanup_and_user_files(self):
        output = self.root / "output"
        for name in ("daily_20260801.eml", "26/08/daily_20260801.eml", "26/10/daily_20261012.eml",
                     "prompts/daily_20260801.eml", "26/08/user.eml", "26/13/daily_20260801.eml"):
            path = output / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"X")
        self.assertEqual({p.relative_to(output).as_posix() for p in mail_paths(output)},
                         {"daily_20260801.eml", "26/08/daily_20260801.eml", "26/10/daily_20261012.eml"})
        self.assertEqual(storage_status(self.root)["mails"], {"count": 3, "bytes": 3, "oldest": "2026-08-01"})
        self.assertEqual(cleanup(self.root, 90, 30, date(2026, 10, 12)), (0, 2))
        for name in ("prompts/daily_20260801.eml", "26/08/user.eml", "26/13/daily_20260801.eml", "26/10/daily_20261012.eml"):
            self.assertTrue((output / name).exists())

    def test_mail_path_rejects_escapes_and_links(self):
        from unittest.mock import patch
        output = self.root / "output"
        for name in ("../daily_x.eml", "/daily_x.eml", "C:/daily_x.eml", "C:daily_x.eml", "//server/share/daily_x.eml",
                     "26\\10\\daily_x.eml", "26/10/../daily_x.eml", "26/00/daily_x.eml", "prompts/daily_x.eml"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                mail_path(output, name)
        self.assertEqual(mail_path(output, "26/10/daily_x.eml"), output / "26/10/daily_x.eml")
        for blocked in (output, output / "26", output / "26/10", output / "26/10/daily_x.eml"):
            with patch.object(Path, "is_symlink", lambda p: p == blocked), self.assertRaises(ValueError):
                mail_path(output, "26/10/daily_x.eml")
        outside = self.root / "outside"
        (output / "26/10").mkdir(parents=True, exist_ok=True)  # 밖을 가리키는 검사는 실제로 있는 파일에 한다
        (output / "26/10/daily_x.eml").write_bytes(b"x")
        original = Path.resolve
        with patch.object(Path, "resolve", lambda p, *a, **k: outside if p.name == "daily_x.eml" else original(p, *a, **k)), self.assertRaises(ValueError):
            mail_path(output, "26/10/daily_x.eml")

    def test_monthly_log_retains_relative_name(self):
        self.log.write_text(LOG.replace("daily_20261012_1500.eml", "26/10/daily_20261012_1500.eml"), encoding="utf-8")
        self.assertIn("26/10/daily_20261012_1500.eml", [r.mail_file for r in load_runs(self.root / "logs")])

    def test_cleanup_only_old_daily_files(self):
        names = {"logs": ["daily_20260101.log", "daily_20261001.log", "other.log", "settings_changes.log"],
                 "output": ["daily_20260801.eml", "daily_20260801_0800.eml", "daily_20261010_preview.eml",
                            "newsletter_mail_preview.eml"]}
        for folder, files in names.items():
            for name in files:
                (self.root / folder / name).write_text("x", encoding="utf-8")
        removed = cleanup(self.root, 90, 30, date(2026, 10, 12))
        self.assertEqual(removed, (1, 2))
        left = {p.name for folder in names for p in (self.root / folder).iterdir()}
        self.assertNotIn("daily_20260101.log", left)
        self.assertTrue({"daily_20261001.log", "other.log", "settings_changes.log", "daily_20261010_preview.eml",
                         "newsletter_mail_preview.eml", "daily_20261012.log"} <= left)
        self.assertEqual(storage_status(self.root)["logs"]["count"], 2)

    def test_change_log_round_trip(self):
        path = self.root / "logs" / "settings_changes.log"
        append_change(path, {"time": ("08:00", "15:00")}, True)
        append_change(path, {"send": (True, False)}, False)
        records = read_changes(path)
        self.assertEqual(records[0]["changes"], {"send": [True, False]})  # 최신 먼저
        self.assertTrue(records[1]["reregistered"])


if __name__ == "__main__":
    unittest.main()
