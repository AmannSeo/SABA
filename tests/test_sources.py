"""RSS Source 설정 파일 (D-073)."""

from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest

from saba import issues, rss
from saba.daily import DailyConfig, test_task_command
from saba.rss import (KST, MAX_SOURCES, RssError, load_source_entries, parse_sources, reload_sources,
                      save_source_entries, source_row)

ROW = {"id": "example-feed", "name": "예시", "url": "https://example.com/rss.xml", "region": "해외"}


class SourceConfigTests(unittest.TestCase):
    def test_repository_file_keeps_original_six(self):  # 코드에서 옮긴 값이 그대로인지 (D-073)
        entries = load_source_entries()[:6]
        self.assertEqual([e.source.source_id for e in entries],
                         ["cert-eu-security-advisories", "boho-security-notice", "cisa-cybersecurity-advisories",
                          "the-hacker-news", "boannews", "boho-report-guide"])
        boannews = next(e.source for e in entries if e.source.source_id == "boannews")
        self.assertEqual((boannews.local_offset, boannews.region, boannews.official, boannews.date_only, boannews.kind),
                         (KST, "국내", False, False, "보안 전문 매체"))
        self.assertTrue(all(e.enabled for e in entries))

    def test_validation(self):
        self.assertEqual(parse_sources([ROW])[0].source.source_name, "예시")
        for bad in ({"id": "A"}, {"id": "has space"}, {"url": "http://example.com"}, {"url": "ftp://x"},
                    {"region": "AI"}, {"name": ""}):
            with self.subTest(bad=bad), self.assertRaises(RssError):
                parse_sources([{**ROW, **bad}])
        with self.assertRaises(RssError):
            parse_sources([ROW, ROW])  # 중복 ID
        with self.assertRaises(RssError):
            parse_sources([{**ROW, "id": f"feed-{i:02d}"} for i in range(MAX_SOURCES + 1)])

    def test_save_round_trip_and_reload_hides_deleted(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "sources.json"
            entries = load_source_entries()
            save_source_entries(entries, path)
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), [source_row(e) for e in entries])
            # 중지는 수집 대상에서만 빠지고, 삭제는 표시용 목록에서도 빠진다.
            rows = [source_row(e) for e in entries if e.source.source_id != "boannews"]
            rows[0]["enabled"] = False
            path.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
            try:
                reload_sources(path)
                self.assertNotIn("cert-eu-security-advisories", [s.source_id for s in rss.SOURCES])
                self.assertIn("cert-eu-security-advisories", issues.SOURCE_BY_ID)  # 같은 dict 를 고쳐 쓴다
                self.assertNotIn("boannews", issues.SOURCE_BY_ID)
            finally:
                reload_sources()
        self.assertIn("boannews", issues.SOURCE_BY_ID)
        self.assertEqual(len(rss.SOURCES), sum(e.enabled for e in load_source_entries()))

    def test_deleted_source_articles_not_selected(self):
        from saba.schema import Article
        now = datetime(2026, 10, 13, 9, 0, tzinfo=timezone.utc)
        base = {"schema_version": 1, "source_name": "x", "original_title": "제목", "url": "https://example.com/a",
                "collection_method": "rss", "collected_at": now.isoformat(), "published_at": now.isoformat()}
        known = Article.model_validate({**base, "article_id": "boannews:1", "source_id": "boannews"})
        gone = Article.model_validate({**base, "article_id": "deleted-feed:1", "source_id": "deleted-feed",
                                       "url": "https://example.com/b"})
        selection = issues.select_issues([known, gone], now)
        self.assertEqual([i.representative.article_id for i in selection.issues], ["boannews:1"])


class SourceKindAndDateTests(unittest.TestCase):  # D-074
    def test_kind_validation_and_official_flag(self):
        entry = parse_sources([{**ROW, "kind": "공식 기관"}])[0]
        self.assertTrue(entry.source.official)
        self.assertFalse(parse_sources([{**ROW, "kind": "IT 언론"}])[0].source.official)
        with self.assertRaises(RssError):
            parse_sources([{**ROW, "kind": "블로그"}])

    def test_dotted_date_in_korean_time(self):
        from saba.rss import publication_time
        self.assertEqual(publication_time("2026.10.12", KST), datetime(2026, 10, 11, 15, 0, tzinfo=timezone.utc))
        self.assertIsNone(publication_time("2026.10.12"))  # 시간대 정보 없고 한국 시간 해석도 꺼짐


class TestTaskTests(unittest.TestCase):
    def test_one_time_task_separate_from_daily(self):
        command = test_task_command(datetime(2026, 10, 12, 15, 50), Path("python.exe"))
        self.assertIn("-Once -At '2026-10-12T15:50:00'", command)
        self.assertIn("'SABA_Test_Send'", command)
        self.assertIn("-m saba.daily --run --test", command)
        self.assertNotIn("SABA_Daily_Briefing", command)


if __name__ == "__main__":
    unittest.main()
