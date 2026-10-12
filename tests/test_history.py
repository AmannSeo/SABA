from datetime import date
from pathlib import Path
import tempfile
import unittest

from saba.history import append_change, cleanup, load_runs, parse_runs, read_changes, read_log, storage_status

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

    def test_load_runs_newest_first(self):
        starts = [r.start for r in load_runs(self.root / "logs")]
        self.assertEqual(starts, sorted(starts, reverse=True))

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
