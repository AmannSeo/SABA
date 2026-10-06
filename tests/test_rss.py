from contextlib import closing
from datetime import datetime, timedelta, timezone
from email.message import Message
import io
import http.client
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch
import urllib.error
import xml.etree.ElementTree as ET

from saba.__main__ import main
from saba.rss import (
    FEED_URL, MAX_BYTES, NoRedirect, RssError, fetch_feed, parse_feed,
    publication_time, reconcile_articles, select_articles,
)
from saba.schema import Article
from saba.storage import StorageError, get_article, list_articles, save_articles

ROOT = Path(__file__).resolve().parents[1]
PAYLOAD = (ROOT / "tests/fixtures/cert_eu_rss.xml").read_bytes()
NOW = datetime(2026, 10, 6, 12, tzinfo=timezone.utc)


def modified(field, value):
    root = ET.fromstring(PAYLOAD)
    element = root.find("channel/item/" + field)
    if value is None:
        root.find("channel/item").remove(element)
    else:
        element.text = value
    return ET.tostring(root, encoding="utf-8")


class MappingTests(unittest.TestCase):
    def setUp(self):
        self.articles = parse_feed(PAYLOAD, NOW)

    def test_mapping_common_schema_and_no_classification(self):
        self.assertEqual(len(self.articles), 2)
        for article in self.articles:
            self.assertEqual(Article.model_validate_json(article.model_dump_json()), article)
            self.assertEqual(article.source_name, "CERT-EU")
            self.assertEqual(article.collection_method, "rss")
            for field in ("category", "summary", "importance", "extracted_text", "canonical_url", "updated_at", "evidence_status", "analysis_metadata"):
                self.assertIsNone(getattr(article, field))
            self.assertEqual(article.departments, [])
        self.assertEqual(self.articles[0].published_at.hour, 8)
        self.assertIn("가상 설명", self.articles[0].feed_excerpt)

    def test_id_stable_across_time_and_title(self):
        other = parse_feed(modified("title", "[가상] 변경 제목"), NOW + timedelta(hours=1))
        self.assertEqual(other[0].article_id, self.articles[0].article_id)
        self.assertNotEqual(other[0].collected_at, self.articles[0].collected_at)

    def test_guid_fallback_preserves_query(self):
        first = parse_feed(modified("guid", None), NOW)[0]
        self.assertIsNone(first.source_item_id)
        self.assertIn("?a=1&b=2", str(first.url))
        root = ET.fromstring(modified("guid", None))
        root.find("channel/item/link").text = "https://example.com/fictional/one?a=9&b=2"
        second = parse_feed(ET.tostring(root), NOW)[0]
        self.assertNotEqual(first.article_id, second.article_id)

    def test_required_and_invalid_urls(self):
        for field, value in (("title", None), ("title", " "), ("link", None), ("link", "ftp://example.com")):
            with self.subTest(field=field, value=value), self.assertRaises(RssError):
                parse_feed(modified(field, value), NOW)

    def test_timezones_and_unknown(self):
        for zone, hour in (("CET", 9), ("CEST", 8), ("+0900", 1), ("GMT", 10), ("UTC", 10), ("+0000", 10)):
            with self.subTest(zone=zone):
                value = publication_time("Tue, 06 Oct 2026 10:00:00 " + zone)
                self.assertEqual(value.hour, hour)
                self.assertEqual(value.tzinfo, timezone.utc)
        for value in (None, "", "invalid", "Tue, 06 Oct 2026 10:00:00", "Tue, 06 Oct 2026 10:00:00 XYZ", "2026-10-06"):
            self.assertIsNone(publication_time(value))
        self.assertIsNone(parse_feed(modified("pubDate", None), NOW)[0].published_at)

    def test_invalid_feed_and_entity(self):
        for payload in (b"<", b"<html/>", b'<rss version="1.0"><channel/></rss>', b'<rss version="2.0"/>', b'<!DOCTYPE rss [<!ENTITY x "unsafe">]><rss version="2.0"><channel/></rss>', PAYLOAD.decode().encode("utf-16")):
            with self.subTest(payload=payload[:30]), self.assertRaises(RssError):
                parse_feed(payload, NOW)

    def test_duplicate_id_is_not_overwritten(self):
        root = ET.fromstring(PAYLOAD)
        root.find("channel").append(ET.fromstring(ET.tostring(root.find("channel/item"))))
        with self.assertRaises(RssError):
            parse_feed(ET.tostring(root), NOW)

    def test_empty_feed(self):
        self.assertEqual(parse_feed(b'<rss version="2.0"><channel/></rss>', NOW), [])

    def test_window_boundaries_future_unknown(self):
        base = self.articles[0]
        for bootstrap, days in ((False, 1), (True, 30)):
            start = NOW - timedelta(days=days)
            values = [start - timedelta(seconds=1), start, NOW, NOW + timedelta(seconds=1), None]
            articles = [base.model_copy(update={"article_id": str(i), "published_at": date}) for i, date in enumerate(values)]
            selected, counts = select_articles(articles, NOW, bootstrap=bootstrap)
            self.assertEqual({a.article_id for a in selected}, {"1", "2", "4"})
            self.assertEqual(counts["excluded"], 2)
            self.assertEqual(counts["unknown"], 1)

    def test_recovery_overlap_cap_and_invalid(self):
        base = self.articles[0]
        for since, start in ((NOW - timedelta(days=2), NOW - timedelta(days=2, hours=6)), (NOW - timedelta(days=20), NOW - timedelta(days=7))):
            items = [base.model_copy(update={"article_id": str(i), "published_at": date}) for i, date in enumerate((start, start - timedelta(seconds=1)))]
            selected, _ = select_articles(items, NOW, since=since)
            self.assertEqual([a.article_id for a in selected], ["0"])
        for since in (NOW.replace(tzinfo=None), NOW + timedelta(seconds=1)):
            with self.assertRaises(RssError):
                select_articles([], NOW, since=since)
        with self.assertRaises(RssError):
            select_articles([], NOW, bootstrap=True, since=NOW)

    def test_limit_and_small_feed(self):
        items = [self.articles[0].model_copy(update={"article_id": str(i)}) for i in range(35)]
        selected, counts = select_articles(items, NOW)
        self.assertEqual(len(selected), 30)
        self.assertEqual(counts["limited"], 5)
        self.assertEqual(len(select_articles(self.articles, NOW)[0]), 1)


class HttpTests(unittest.TestCase):
    def response(self, payload=PAYLOAD, content_type="text/xml", status=200, encoding=None):
        response = MagicMock()
        response.__enter__.return_value = response
        response.status = status
        response.headers = Message()
        response.headers["Content-Type"] = content_type
        if encoding:
            response.headers["Content-Encoding"] = encoding
        response.read.return_value = payload
        return response

    def test_one_bounded_request(self):
        response = self.response()
        with patch("saba.rss.urllib.request.build_opener") as factory:
            factory.return_value.open.return_value = response
            self.assertEqual(fetch_feed(), PAYLOAD)
            request = factory.return_value.open.call_args.args[0]
            self.assertEqual(request.full_url, FEED_URL)
            self.assertEqual(factory.return_value.open.call_args.kwargs["timeout"], 15)
            factory.return_value.open.assert_called_once()
            response.read.assert_called_once_with(MAX_BYTES + 1)

    def test_timeout_http_redirect_and_safe_errors(self):
        errors = [TimeoutError("DO_NOT_LOG_RAW_BODY"), urllib.error.URLError("DO_NOT_LOG_RAW_BODY"), urllib.error.HTTPError(FEED_URL, 403, "DO_NOT_LOG_RAW_BODY", {}, None), urllib.error.HTTPError(FEED_URL, 302, "redirect", {}, None)]
        for error in errors:
            with self.subTest(error=type(error).__name__), patch("saba.rss.urllib.request.build_opener") as factory:
                factory.return_value.open.side_effect = error
                with self.assertRaises(RssError) as caught:
                    fetch_feed()
                self.assertNotIn("DO_NOT_LOG_RAW_BODY", str(caught.exception))
                factory.return_value.open.assert_called_once()
        self.assertIsNone(NoRedirect().redirect_request(None, None, 302, "", {}, "https://example.com"))

    def test_unexpected_responses_and_size(self):
        for response in (self.response(content_type="text/html"), self.response(status=204), self.response(encoding="gzip"), self.response(payload=b"x" * (MAX_BYTES + 1))):
            with patch("saba.rss.urllib.request.build_opener") as factory:
                factory.return_value.open.return_value = response
                with self.assertRaises(RssError):
                    fetch_feed()

    def test_read_timeout_is_safe(self):
        response = self.response()
        response.read.side_effect = TimeoutError("DO_NOT_LOG_RAW_BODY")
        with patch("saba.rss.urllib.request.build_opener") as factory:
            factory.return_value.open.return_value = response
            with self.assertRaises(RssError):
                fetch_feed()

    def test_truncated_http_is_safe(self):
        response = self.response()
        response.read.side_effect = http.client.IncompleteRead(b"DO_NOT_LOG_RAW_BODY", 20)
        with patch("saba.rss.urllib.request.build_opener") as factory:
            factory.return_value.open.return_value = response
            with self.assertRaises(RssError) as caught:
                fetch_feed()
        self.assertNotIn("DO_NOT_LOG_RAW_BODY", str(caught.exception))


class StorageAndCliTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="saba-rss-", dir=ROOT / ".venv")
        self.addCleanup(self.temporary.cleanup)
        self.db = Path(self.temporary.name) / "nested" / "rss.db"

    def cli(self, *args, payload=PAYLOAD, now=NOW):
        clock = MagicMock()
        clock.now.return_value = now
        clock.fromisoformat.side_effect = datetime.fromisoformat
        with patch.object(sys, "argv", ["saba", *map(str, args)]), patch("saba.__main__.fetch_feed", return_value=payload) as fetch, patch("saba.__main__.datetime", clock):
            result = main()
        return result, fetch.call_count

    def test_first_save_reconnect_repeat_and_optional_preservation(self):
        self.assertEqual(self.cli("--collect-rss", "--bootstrap", "--db", self.db), (0, 1))
        articles = list_articles(self.db)
        self.assertEqual(len(articles), 2)
        original = articles[0]
        # 기존 선택 정보가 있는 DB를 임시 공간에 준비한다.
        original.summary = "가상 기존 분석 정보"
        original.category = "가상 기존 분류"
        with closing(sqlite3.connect(self.db)) as connection:
            with connection:
                connection.execute("UPDATE articles SET article_json = ? WHERE article_id = ?", (original.model_dump_json(), original.article_id))
            stored = connection.execute("SELECT article_id, stored_at FROM articles ORDER BY article_id").fetchall()
        before = self.db.read_bytes()
        with self.assertLogs(level="INFO") as logs:
            self.assertEqual(self.cli("--collect-rss", "--bootstrap", "--db", self.db, now=NOW + timedelta(hours=1)), (0, 1))
        self.assertIn("신규 0건 · 동일 원문 2건 생략", "\n".join(logs.output))
        self.assertEqual(self.db.read_bytes(), before)
        self.assertEqual(get_article(self.db, original.article_id), original)
        with closing(sqlite3.connect(self.db)) as connection:
            self.assertEqual(connection.execute("SELECT article_id, stored_at FROM articles ORDER BY article_id").fetchall(), stored)
        query = subprocess.run([sys.executable, "-X", "utf8", "-m", "saba", "--list-articles", "--db", str(self.db)], cwd=ROOT, capture_output=True, encoding="utf-8")
        self.assertEqual(query.returncode, 0)
        self.assertIn("저장 기사 2건", query.stdout)

    def test_conflict_holds_new_article_and_safe_log(self):
        self.cli("--collect-rss", "--bootstrap", "--db", self.db)
        before = self.db.read_bytes()
        root = ET.fromstring(modified("description", "DO_NOT_LOG_RAW_BODY"))
        new = ET.fromstring(ET.tostring(root.find("channel/item")))
        new.find("guid").text = "fictional-new-before-conflict"
        root.find("channel").insert(0, new)
        with self.assertLogs(level="ERROR") as logs:
            self.assertEqual(self.cli("--collect-rss", "--bootstrap", "--db", self.db, payload=ET.tostring(root))[0], 1)
        self.assertIn("충돌 1건", "\n".join(logs.output))
        self.assertNotIn("DO_NOT_LOG_RAW_BODY", "\n".join(logs.output))
        self.assertEqual(self.db.read_bytes(), before)

    def test_dry_run_absent_and_existing_db(self):
        self.assertEqual(self.cli("--collect-rss", "--dry-run", "--bootstrap", "--db", self.db), (0, 1))
        self.assertFalse(self.db.parent.exists())
        self.cli("--collect-rss", "--bootstrap", "--db", self.db)
        before = self.db.read_bytes()
        self.assertEqual(self.cli("--collect-rss", "--dry-run", "--bootstrap", "--db", self.db), (0, 1))
        self.assertEqual(self.db.read_bytes(), before)

    def test_zero_candidates_creates_no_db(self):
        payload = b'<rss version="2.0"><channel/></rss>'
        self.assertEqual(self.cli("--collect-rss", "--db", self.db, payload=payload), (0, 1))
        self.assertFalse(self.db.parent.exists())

    def test_invalid_feed_creates_no_db_and_safe_logs(self):
        for payload in (b"<DO_NOT_LOG_RAW_BODY", modified("title", " ")):
            with self.assertLogs(level="ERROR") as logs:
                self.assertEqual(self.cli("--collect-rss", "--db", self.db, payload=payload)[0], 1)
            self.assertNotIn("DO_NOT_LOG_RAW_BODY", "\n".join(logs.output))
        self.assertFalse(self.db.parent.exists())

    def test_unknown_date_stored_as_null_not_latest(self):
        payload = modified("pubDate", "unknown")
        self.assertEqual(self.cli("--collect-rss", "--db", self.db, payload=payload), (0, 1))
        restored = list_articles(self.db)
        self.assertEqual(len(restored), 1)
        self.assertIsNone(restored[0].published_at)
        self.assertEqual(restored[0].collected_at, NOW)
        with closing(sqlite3.connect(self.db)) as connection:
            self.assertIsNone(connection.execute("SELECT published_at FROM articles").fetchone()[0])

    def test_network_error_cli_safe_no_db(self):
        with patch.object(sys, "argv", ["saba", "--collect-rss", "--db", str(self.db)]), patch("saba.__main__.fetch_feed", side_effect=RssError("RSS 네트워크 요청 실패")), self.assertLogs(level="ERROR") as logs:
            self.assertEqual(main(), 1)
        self.assertNotIn("Traceback", "\n".join(logs.output))
        self.assertFalse(self.db.parent.exists())

    def test_auxiliary_options_and_since(self):
        for args in (("--dry-run",), ("--bootstrap",), ("--since", NOW.isoformat()), ("--collect-rss", "--bootstrap", "--since", NOW.isoformat()), ("--collect-rss", "--since", "2026-10-06"), ("--collect-rss", "--since", (NOW + timedelta(seconds=1)).isoformat()), ("--collect-rss", "--list-articles")):
            with self.subTest(args=args), patch("sys.stderr", new_callable=io.StringIO), self.assertRaises(SystemExit) as caught:
                self.cli(*args)
            self.assertEqual(caught.exception.code, 2)
        self.assertEqual(self.cli("--collect-rss", "--dry-run", "--since", (NOW - timedelta(days=2)).isoformat(), "--db", self.db), (0, 1))

    def test_default_validation_preserve_db_and_no_network(self):
        for exists in (False, True):
            if exists:
                save_articles(self.db, parse_feed(PAYLOAD, NOW))
            before = self.db.read_bytes() if exists else None
            with patch("saba.__main__.DEFAULT_DB", self.db):
                for args in ((), ("--validate-json", ROOT / "tests/fixtures/news_valid.json")):
                    self.assertEqual(self.cli(*args), (0, 0))
            self.assertEqual(self.db.read_bytes() if self.db.exists() else None, before)


if __name__ == "__main__":
    unittest.main()
