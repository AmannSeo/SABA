import json
from pathlib import Path
import tempfile
import unittest

from saba.analysis_storage import list_analyses
from saba.briefing import analyze_issues
from saba.issues import select_issues
from saba.notice_body import body_excerpt, notice_excerpts
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


if __name__ == "__main__":
    unittest.main()
