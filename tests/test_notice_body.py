import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from saba.analysis_storage import list_analyses
from saba.briefing import analyze_issues
from saba.issues import select_issues
from saba.notice_body import body_excerpt, notice_excerpts
from saba import notice_body, crawl
from saba.schema import validate_articles
from saba.storage import list_articles, save_articles
from test_briefing import NOW, FakeRun, response, row

URL = "https://www.boho.or.kr/kr/bbs/view.do?bbsId=B0000133&nttId=1"
BODY = "가상 제품에서 원격 코드 실행 취약점이 확인됐습니다."
PAGE = ('<div class="board"><div class="content"><div class="content_html"><p>□ 개요<br>o ' + BODY +
        '<br>o a &lt;b&gt; 업데이트 권고</p><script>x()</script></div><div class="content">끝</div>').encode()


class NoticeBodyTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.dir = Path(temp.name)
        data = row("boho", "boho-security-notice", "[가상] 보안 업데이트 권고", excerpt=None) | {"url": URL}
        self.article = validate_articles([data])[0]

    def test_excerpt_lines_become_sentences_and_stay_escaped(self):
        self.assertEqual(body_excerpt(PAGE), f"□ 개요. o {BODY} o a &lt;b&gt; 업데이트 권고.")
        self.assertIsNone(body_excerpt(b"<html>no content</html>"))

    def test_fetch_once_then_cache_and_no_fetch_mode(self):
        cache, calls = self.dir / "bodies.json", []
        fetcher = lambda url: calls.append(url) or PAGE
        first = notice_excerpts([self.article], cache_path=cache, fetcher=fetcher)
        second = notice_excerpts([self.article], cache_path=cache, fetcher=fetcher)
        self.assertEqual(first, second)
        self.assertEqual(calls, [URL])  # 같은 URL 은 다시 가져오지 않는다
        self.assertEqual(notice_excerpts([self.article], cache_path=self.dir / "none.json", fetch=False,
                                         fetcher=fetcher), {})
        other = self.article.model_copy(update={"url": "https://example.com/x"})  # 보호나라 공지 URL 만
        self.assertEqual(notice_excerpts([other], cache_path=self.dir / "o.json", fetcher=fetcher), {})
        self.assertEqual(json.loads(cache.read_text(encoding="utf-8"))[URL], first["boho"])

    def test_body_excerpt_analyzed_and_saved_without_changing_article_db(self):
        article_db, analysis_db = self.dir / "saba.db", self.dir / "analysis.db"
        save_articles(article_db, [self.article])
        excerpts = {"boho": f"{BODY}"}
        plan = {"boho": response() | {"evidence": [{"input_field": "feed_excerpt", "quote": BODY, "target": t}
                                                    for t in ("newsletter_title", "summary", "category",
                                                              "importance_reason", "tags[0]", "key_points[0]")]}}
        plan["boho"]["summary"] = plan["boho"]["summary"].replace("가상 출처에 따르면 가상 웹 서버에서", "가상 출처에 따르면")
        results, stats = analyze_issues(select_issues([self.article], NOW).issues, article_db, analysis_db,
                                        ledger_path=self.dir / "usage.json", run=FakeRun(plan), excerpts=excerpts)
        self.assertEqual((stats.valid, stats.insufficient), (1, 0))
        self.assertEqual(len(list_analyses(analysis_db)), 1)
        self.assertIsNone(list_articles(article_db)[0].feed_excerpt)  # 기사 DB 불변

    def test_moel_body_scoped_bounded_and_cached_without_attachments(self):
        url = "https://www.moel.go.kr/news/enews/report/enewsView.do?news_seq=123"
        article = self.article.model_copy(update={"source_id": "moel-press", "url": url})
        page = ('<div>navigation</div><div class=" b_content news_content"><p>' + BODY +
                '</p><div>추가 본문.</div><script>hidden()</script></div>'
                '<div class="files"><a href="/download.hwpx">attachment</a></div>').encode()
        cache = self.dir / 'moel.json'
        with patch.object(crawl, 'allowed', return_value=True) as robots, \
                patch.object(crawl, '_get', return_value=(200, 'text/html', page)) as get:
            first = notice_excerpts([article], cache_path=cache)
            self.assertEqual(notice_excerpts([article], cache_path=cache), first)
            get.assert_called_once_with(url, redirects=False)
            robots.assert_called_once_with(url)
        self.assertIn(BODY, first[article.article_id])
        for hidden in ('navigation', 'hidden', 'attachment'):
            self.assertNotIn(hidden, first[article.article_id])
        huge = ('<div class="b_content news_content">' + 'x' * 1500 + '</div>').encode()
        self.assertLessEqual(len(body_excerpt(huge, 'moel')), notice_body.EXCERPT_CHARS)

    def test_detail_fetch_rejects_robots_outside_paths_types_and_sizes(self):
        url = "https://www.moel.go.kr/news/enews/report/enewsView.do?news_seq=123"
        with patch.object(crawl, 'allowed', return_value=False), patch.object(crawl, '_get') as get:
            self.assertIsNone(notice_body.fetch_page(url))
            get.assert_not_called()
        for bad in ('http://www.moel.go.kr/news/enews/report/enewsView.do?news_seq=1',
                    'https://www.moel.go.kr/download.pdf', 'https://www.moel.go.kr.evil.test/news/enews/report/enewsView.do?news_seq=1',
                    'https://user@www.moel.go.kr/news/enews/report/enewsView.do?news_seq=1',
                    'https://www.moel.go.kr/news/enews/report/enewsView.do?news_seq=1&news_seq=2',
                    'https://www.moel.go.kr/news/enews/report/enewsView.do?news_seq=x'):
            with patch.object(crawl, 'allowed') as robots, patch.object(crawl, '_get') as get:
                self.assertIsNone(notice_body.fetch_page(bad))
                robots.assert_not_called()
                get.assert_not_called()
        for reply in ((200, 'application/pdf', b'x'), (302, 'text/html', b'x'),
                      (200, 'text/html', b'x' * (notice_body.MAX_BYTES + 1))):
            with patch.object(crawl, 'allowed', return_value=True), patch.object(crawl, '_get', return_value=reply):
                self.assertIsNone(notice_body.fetch_page(url))

    def test_body_analysis_remains_in_strict_newsletter(self):
        from saba.briefing import build_views
        article_db, analysis_db = self.dir / 'articles.db', self.dir / 'analyses.db'
        save_articles(article_db, [self.article])
        cache = self.dir / 'cache.json'
        notice_excerpts([self.article], cache_path=cache, fetcher=lambda url: PAGE)
        excerpts = notice_excerpts([self.article], cache_path=cache, fetch=False)
        from saba.ai_adapter import prepare_request
        text = prepare_request(self.article.model_copy(update={"feed_excerpt": excerpts[self.article.article_id]})).request.snapshot.texts['feed_excerpt']
        plan = response()
        plan['evidence'] = [{'input_field': 'feed_excerpt', 'quote': text, 'target': t}
                            for t in ('newsletter_title', 'summary', 'category', 'importance_reason', 'tags[0]', 'key_points[0]')]
        views, _, stats = build_views(article_db, analysis_db, NOW, body_cache=cache, insight_db=self.dir/'insights.db',
                                      ledger_path=self.dir/'usage.json', analyzed_only=True, run=FakeRun({'boho': plan}))
        self.assertEqual([v.article_id for v in views], ['boho'])
        self.assertEqual(stats.dropped_unanalyzed, 0)


if __name__ == "__main__":
    unittest.main()
