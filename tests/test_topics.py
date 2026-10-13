"""F13: Atom 피드, 본문 안 DOCTYPE 글자, 주제 Source 의 수집·표시 기간과 상한 묶음, 메일 섹션."""
from datetime import datetime, timedelta, timezone
import unittest
from unittest.mock import patch

from saba import issues, newsletter
from saba.rss import RssError, Source, parse_feed, select_articles
from saba.schema import validate_articles

NOW = datetime(2026, 10, 14, 0, tzinfo=timezone.utc)  # 수요일 (KST 09:00)
TESTING = Source("virtual-testing", "가상 테스트 블로그", "https://example.com/feed", region="해외",
                 kind="기업·벤더", topic="테스트")
SECURITY = Source("virtual-security", "가상 보안 매체", "https://example.com/sec", region="해외")
ATOM = b"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"><title>v</title>
<entry><id>tag:example.com,2026:1</id><title>v1.0.0</title><link rel="alternate" href="https://example.com/r/1"/>
<updated>2026-10-12T03:00:00Z</updated><content type="html">&lt;p&gt;release notes&lt;/p&gt;</content></entry>
</feed>"""


def article(source, hours_old, collected_hours_ago, key="a"):
    return validate_articles([{
        "schema_version": 1, "article_id": f"{source.source_id}:{key * 64}"[:len(source.source_id) + 65],
        "source_id": source.source_id, "source_name": source.source_name, "original_title": f"[가상] {key}",
        "url": f"https://example.com/{key}", "collection_method": "rss", "source_item_id": None,
        "collected_at": (NOW - timedelta(hours=collected_hours_ago)).isoformat(),
        "published_at": (NOW - timedelta(hours=hours_old)).isoformat(), "feed_excerpt": None}])[0]


class TopicTests(unittest.TestCase):
    def test_atom_feed_is_parsed_like_rss(self):
        [item] = parse_feed(ATOM, NOW, TESTING)
        self.assertEqual((item.original_title, str(item.url)), ("v1.0.0", "https://example.com/r/1"))
        self.assertEqual(item.published_at, datetime(2026, 10, 12, 3, tzinfo=timezone.utc))

    def test_doctype_text_in_body_is_not_a_declaration(self):
        body = (b'<?xml version="1.0"?><rss version="2.0"><channel><item><title>t</title><link>https://example.com/x</link>'
                b'<description>&lt;!DOCTYPE html&gt; sample code</description></item></channel></rss>')
        self.assertEqual(len(parse_feed(body, NOW, SECURITY)), 1)
        with self.assertRaises(RssError):
            parse_feed(b'<?xml version="1.0"?><!DOCTYPE rss [<!ENTITY x "y">]><rss version="2.0"><channel/></rss>', NOW, SECURITY)

    def test_topic_sources_keep_seven_days_and_security_keeps_one(self):
        old = article(TESTING, 24 * 5, 0)
        self.assertEqual(len(select_articles([old], NOW, wide=True)[0]), 1)
        self.assertEqual(len(select_articles([old], NOW)[0]), 0)

    def test_topic_article_shown_only_on_first_collection(self):
        with patch.dict(issues.SOURCE_BY_ID, {TESTING.source_id: TESTING, SECURITY.source_id: SECURITY}):
            self.assertTrue(issues.in_window(article(TESTING, 24 * 5, 1), NOW))       # 5일 전 글, 방금 처음 수집
            self.assertFalse(issues.in_window(article(TESTING, 24 * 5, 30), NOW))     # 어제 이미 수집 → 반복하지 않음
            self.assertFalse(issues.in_window(article(TESTING, 24 * 8, 1), NOW))      # 7일 넘은 글
            self.assertFalse(issues.in_window(article(SECURITY, 30, 1), NOW))         # 보안 Source 는 발행 24시간 그대로
            self.assertEqual((issues.section_key(TESTING), issues.section_key(SECURITY)), ("테스트", "해외"))

    def test_topic_source_goes_to_topic_section(self):
        with patch.dict(newsletter.SOURCE_BY_ID, {TESTING.source_id: TESTING}):
            view = newsletter.build_article_view(article(TESTING, 2, 1))
        self.assertEqual(newsletter.article_section(view), "testing")
        html = newsletter.build_newsletter_html([view])
        self.assertIn("테스트", html)


if __name__ == "__main__":
    unittest.main()
