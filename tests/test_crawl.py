"""D-078 웹페이지 수집: 사이트별 목록 파서, robots.txt, 요청 간격, 형식 변경 감지, 다른 사이트 리다이렉트."""
from datetime import datetime, timezone
import unittest
from unittest.mock import patch
import urllib.request

from saba import crawl
from saba.rss import METHODS, RssError, Source

NOW = datetime(2026, 10, 14, 0, tzinfo=timezone.utc)
BIZINFO = """<table><tbody><tr><td>1</td><td> 기술 </td><td class="txt_l"><a href="/sii/siia/selectSIIA200Detail.do?rows=15&amp;pblancId=PBLN_000000000000001"
 title="x">[가상] AI 바우처 공고</a></td><td> 2026-10-07 ~ 2026-10-23 </td><td>과학기술정보통신부</td><td>가상진흥원</td><td>2026-10-13</td><td>1</td></tr></tbody></table>"""
MOEL = """<tbody><tr><td>1</td><td><strong><a href="enewsView.do?news_seq=7" title="t">[가상] 근로시간 제도 개편</a></strong></td>
<td aria-label="첨부"></td><td aria-label="등록일">2026.10.13</td></tr></tbody>"""
NTS = """<tbody><tr><td data-table="number">1</td><td data-table="subject"><a href="javascript:;" data-id="99" title="t" class="nttInfoBtn"> [가상] 연말정산 안내</a></td>
<td data-table="write"> <!-- 주석 --> 법인세과</td><td data-table="date">2026.10.12.</td></tr></tbody>"""
IRIS = """<ul><li> <span class="inst_title">가상부 > 가상평가원</span> <div class="group1"><strong class="title">
<a href="" onclick="f_bsnsAncmBtinSituListForm_view('000123','ancmIng'); return false;">[가상] R&amp;D 신규과제 공고</a></strong>
<div class="etc_info"><span><em>공고번호 :</em>가상-1</span> <span class="ancmDe"><em>공고일자 :</em>2026-10-12</span>
<span><em>공고상태 :</em> 공고접수중 </span></div></div></li></ul>"""


def source(method, url="https://www.example.go.kr/list.do?mi=1&bbsId=2"):
    return Source("virtual-crawl", "가상 기관", url, date_only=True, region="국내", kind="공식 기관", topic="사업", method=method)


class CrawlTests(unittest.TestCase):
    def setUp(self):
        crawl._robots.clear()
        crawl._last_request.clear()

    def test_methods_match_parsers(self):
        self.assertEqual(set(METHODS) - {"rss"}, set(crawl.PARSERS))

    def test_site_parsers(self):
        cases = {"crawl:bizinfo": (BIZINFO, "[가상] AI 바우처 공고", "pblancId=PBLN_000000000000001", "신청기간 2026-10-07 ~ 2026-10-23"),
                 "crawl:moel": (MOEL, "[가상] 근로시간 제도 개편", "list.do/../enewsView.do" and "enewsView.do?news_seq=7", None),
                 "crawl:nts": (NTS, "[가상] 연말정산 안내", "nttSn=99", "담당 법인세과."),
                 "crawl:iris": (IRIS, "[가상] R&D 신규과제 공고", "ancmId=000123", "공고상태 공고접수중.")}
        for method, (page, title, url_part, excerpt) in cases.items():
            with self.subTest(method=method):
                [item] = crawl.PARSERS[method](page, "https://www.example.go.kr/news/list.do?mi=1&bbsId=2")
                self.assertEqual(item["title"], title)
                self.assertIn(url_part, item["url"])
                if excerpt:
                    self.assertIn(excerpt, item["excerpt"])
                [article] = crawl.articles_from_items([item], NOW, source(method))
                kst_date = article.published_at.astimezone(timezone(crawl.KST))
                self.assertEqual(article.collection_method, "crawl")
                self.assertEqual((kst_date.strftime("%Y%m%d"), kst_date.hour), (item["date"].replace("-", "").replace(".", ""), 0))

    def collect(self, pages: dict, method="crawl:moel"):
        calls = []
        def fake_get(url, **options):
            calls.append(url)
            return pages[url]
        with patch.object(crawl, "_get", side_effect=fake_get):
            return crawl.collect(source(method), NOW), calls

    def test_robots_disallow_stops_before_list_request(self):
        pages = {"https://www.example.go.kr/robots.txt": (200, "text/plain", b"User-agent: *\nDisallow: /list.do\n")}
        with self.assertRaisesRegex(RssError, "robots.txt"):
            self.collect(pages)

    def test_robots_missing_allows_and_unreadable_blocks(self):
        page = (200, "text/html", MOEL.encode())
        articles, calls = self.collect({"https://www.example.go.kr/robots.txt": (404, "", b""),
                                        "https://www.example.go.kr/list.do?mi=1&bbsId=2": page})
        self.assertEqual((len(articles), len(calls)), (1, 2))
        crawl._robots.clear()
        with self.assertRaisesRegex(RssError, "robots.txt"):
            self.collect({"https://www.example.go.kr/robots.txt": (503, "", b"")})

    def test_empty_or_changed_list_is_an_error(self):
        pages = {"https://www.example.go.kr/robots.txt": (404, "", b""),
                 "https://www.example.go.kr/list.do?mi=1&bbsId=2": (200, "text/html", b"<html>new layout</html>")}
        with self.assertRaisesRegex(RssError, "구조가 바뀌었을"):
            self.collect(pages)

    def test_requests_to_same_host_are_spaced(self):
        waits, clock = [], iter([0.0, 0.0, 0.2, 0.2])
        class Response:
            status, headers = 200, None
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def read(self, n): return b"x"
        Response.headers = type("H", (), {"get_content_type": lambda self: "text/html"})()
        with patch.object(urllib.request.OpenerDirector, "open", return_value=Response()):
            crawl._get("https://a.example/1", sleep=waits.append, clock=lambda: next(clock))
            crawl._get("https://a.example/2", sleep=waits.append, clock=lambda: next(clock))
        self.assertEqual(len(waits), 1)
        self.assertAlmostEqual(waits[0], 0.8)

    def test_redirect_to_other_host_refused(self):
        handler = crawl.SameHostRedirect()
        request = urllib.request.Request("https://www.example.go.kr/a")
        with self.assertRaises(RssError):
            handler.redirect_request(request, None, 302, "Found", {}, "https://evil.example/a")


if __name__ == "__main__":
    unittest.main()
