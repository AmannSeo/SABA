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
            self.assertTrue(issues.in_window(article(TESTING, 24 * 5, -0.01), NOW))   # 실행 시작 (now) 뒤 같은 실행에서 수집
            self.assertFalse(issues.in_window(article(TESTING, 24 * 5, 30), NOW))     # 어제 이미 수집 → 반복하지 않음
            self.assertFalse(issues.in_window(article(TESTING, 24 * 8, 1), NOW))      # 7일 넘은 글
            self.assertFalse(issues.in_window(article(SECURITY, 30, 1), NOW))         # 보안 Source 는 발행 24시간 그대로
            self.assertEqual((issues.section_key(TESTING), issues.section_key(SECURITY)), ("테스트", "해외"))

    def test_topic_hint_only_for_topic_sources(self):
        from saba.analysis import InputSnapshot, input_payload
        with patch.dict(issues.SOURCE_BY_ID, {TESTING.source_id: TESTING, SECURITY.source_id: SECURITY}):
            topic, security = input_payload(article(TESTING, 2, 1)), input_payload(article(SECURITY, 2, 1, key="b"))
        self.assertEqual(topic["source_topic"], "SW 테스트·품질")
        self.assertNotIn("source_topic", security)  # 보안 Source 입력·해시는 이전과 같다
        self.assertNotIn("source_topic", InputSnapshot.model_validate(security).model_dump())

    def test_sections_interleaved_for_analysis_budget(self):
        rows = [article(SECURITY, 1 + i, 1, key=f"s{i}") for i in range(3)] + [article(TESTING, 30 + i, 1, key=f"t{i}") for i in range(2)]
        with patch.dict(issues.SOURCE_BY_ID, {TESTING.source_id: TESTING, SECURITY.source_id: SECURITY}):
            order = [issues.section_key(issues.SOURCE_BY_ID[i.representative.source_id]) for i in issues.select_issues(rows, NOW).issues]
        self.assertEqual(order[:4], ["해외", "테스트", "해외", "테스트"])

    def test_github_compact_prerelease_versions_and_stable_word(self):
        tags = ('v1.0.0rc1', 'v1.0.0a1', 'v1.0.0b2', 'alphabet-v1.0.0', 'v1.0.0')
        payload = b'<feed xmlns="http://www.w3.org/2005/Atom">' + b''.join(
            f'<entry><id>{tag}</id><title>{tag}</title><link href="https://github.com/o/r/releases/tag/{tag}"/><updated>2026-10-13T00:00:00Z</updated></entry>'.encode()
            for tag in tags) + b'</feed>'
        source = Source('virtual-rel', '가상 릴리스', 'https://github.com/o/r/releases.atom', topic='테스트')
        self.assertEqual([a.original_title for a in parse_feed(payload, NOW, source)], ['alphabet-v1.0.0', 'v1.0.0'])

    def test_github_releases_keep_stable_only(self):
        feed = b"""<?xml version="1.0" encoding="UTF-8"?><feed xmlns="http://www.w3.org/2005/Atom">""" + b"".join(
            f'<entry><id>{t}</id><title>{t}</title><link href="https://github.com/o/r/releases/{t}"/><updated>2026-10-13T00:00:00Z</updated></entry>'.encode()
            for t in ("v1.2.0", "v1.3.0-alpha.1", "0.65.0-nightly.20261014", "2026-07-28 RC", "v2.0.0-beta.4", "rust-v0.163.0")) + b"</feed>"
        releases = Source("virtual-rel", "가상 릴리스", "https://github.com/o/r/releases.atom", topic="AI")
        self.assertEqual([a.original_title for a in parse_feed(feed, NOW, releases)], ["v1.2.0", "rust-v0.163.0"])
        other = Source("virtual-atom", "가상 Atom", "https://example.com/feed.atom")
        self.assertEqual(len(parse_feed(feed, NOW, other)), 6)  # GitHub 릴리스가 아니면 거르지 않는다

    def test_ai_topic_goes_to_ai_section(self):
        ai = Source("virtual-ai", "가상 AI 도구", "https://example.com/ai", region="해외", kind="기업·벤더", topic="AI")
        with patch.dict(newsletter.SOURCE_BY_ID, {ai.source_id: ai}):
            view = newsletter.build_article_view(article(ai, 2, 1))
        self.assertEqual(newsletter.article_section(view), "ai_tech")
        from saba.analysis import input_payload
        with patch.dict(issues.SOURCE_BY_ID, {ai.source_id: ai}):
            self.assertEqual(input_payload(article(ai, 2, 1))["source_topic"], "AI 개발·도입")

    def test_topic_source_goes_to_topic_section(self):
        with patch.dict(newsletter.SOURCE_BY_ID, {TESTING.source_id: TESTING}):
            view = newsletter.build_article_view(article(TESTING, 2, 1))
        self.assertEqual(newsletter.article_section(view), "testing")
        html = newsletter.build_newsletter_html([view])
        self.assertIn("테스트", html)


if __name__ == "__main__":
    unittest.main()
