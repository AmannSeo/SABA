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
        self.assertEqual({m for m in METHODS if m.startswith("crawl:")}, set(crawl.PARSERS))

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

    def test_additional_sites_use_publication_dates_not_periods(self):
        cases = {
            "crawl:nipa": ('<tr><td>1</td><td><a href="/home/2-2/7"><!-- hidden -->[가상] 사업 공고</a> 신청기간 2026-10-01 ~ 2026-10-30</td><td>담당</td><td><span>2026-10-12</span></td></tr>', 'https://www.nipa.kr/home/2-2/7'),
            "crawl:smtech": ('<tr><td>1</td><td><a href="/front/ifg/no/notice01_detail.do;jsessionid=VIRTUAL?bitmSeq=8&amp;pageIndex=1">[가상] R&amp;D 공지</a></td><td>2026-10-12</td><td>2026-10-14</td></tr>', 'https://www.smtech.go.kr/front/ifg/no/notice01_detail.do?bitmSeq=8'),
            "crawl:kocca": ('<tr><td><a href="/kocca/bbs/view/B0000137/9.do?menuNo=204802">[가상] 콘텐츠 지원 안내</a></td><td data-label="등록일">2026-10-12</td><td>2026-10-20</td></tr>', 'https://www.kocca.kr/kocca/bbs/view/B0000137/9.do?menuNo=204802'),
            "crawl:searchadvisor": ('<a href="https://blog.naver.com/naver_search/6">일반 검색 뉴스 26.10.12</a><a href="https://blog.naver.com/naver_webmaster/10"><b>웹마스터</b> [가상] SEO 정책 공지 <span>26.10.12</span></a>', 'https://blog.naver.com/naver_webmaster/10')}
        bases = {'crawl:nipa': 'https://www.nipa.kr/home/2-2', 'crawl:smtech': 'https://www.smtech.go.kr/front/ifg/no/notice01_list.do',
                 'crawl:kocca': 'https://www.kocca.kr/kocca/bbs/list/B0000137.do?menuNo=204802', 'crawl:searchadvisor': 'https://searchadvisor.naver.com/'}
        for method, (page, expected) in cases.items():
            with self.subTest(method=method):
                [item] = crawl.PARSERS[method](page, bases[method])
                self.assertEqual((item['date'], item['url'], item['excerpt']), ('2026-10-12', expected, None))
                self.assertIn('[가상]', item['title'])
                self.assertNotIn('hidden', item['title'])
                self.assertNotIn('jsessionid', item['url'])
                [article] = crawl.articles_from_items([item], NOW, source(method, bases[method]))
                self.assertEqual(article.collection_method, 'crawl')
                self.assertEqual(crawl.PARSERS[method]('<html>changed</html>', bases[method]), [])
                with patch.object(crawl, 'allowed', return_value=True), patch.object(crawl, '_get', return_value=(200, 'text/html', page.encode())):
                    self.assertEqual(len(crawl.collect(source(method, bases[method]), NOW)), 1)
                with patch.object(crawl, 'allowed', return_value=True), patch.object(crawl, '_get', return_value=(200, 'text/html', b'<html>changed</html>')), self.assertRaises(RssError):
                    crawl.collect(source(method, bases[method]), NOW)

    def test_same_host_redirect_also_observes_interval(self):
        crawl._last_request['www.example.go.kr'] = 10
        request = urllib.request.Request('https://www.example.go.kr/a')
        with patch.object(crawl.time, 'monotonic', side_effect=[10.2, 11.0]), patch.object(crawl.time, 'sleep') as sleep:
            redirected = crawl.SameHostRedirect().redirect_request(request, None, 302, 'Found', {}, 'https://www.example.go.kr/b')
        self.assertEqual(redirected.full_url, 'https://www.example.go.kr/b')
        sleep.assert_called_once()
        self.assertAlmostEqual(sleep.call_args.args[0], .8)

    def test_kiat_summary_keeps_written_date_and_excludes_other_boards(self):
        page = '''<a href="javascript:mainContentsGo('90','abc123')"><p class="tit"><span data-start="2026-10-20"></span>[가상] R&amp;D 공고</p>
                  <img data-written_date="2026-10-12"><span class="data">2026-10-20 ~ 2026-11-30</span></a>
                  <a href="javascript:mainContentsGo('67','def456')"><p class="tit">채용</p><img data-written_date="2026-10-13"></a>'''
        [item] = crawl.parse_kiat(page, 'https://www.kiat.or.kr/front/user/main.do')
        self.assertEqual((item['title'], item['date'], item['excerpt']), ('[가상] R&D 공고', '2026-10-12', None))
        self.assertEqual(item['url'], 'https://www.kiat.or.kr/front/board/boardContentsView.do?board_id=90&contents_id=abc123')
        self.assertEqual(crawl.parse_kiat(page.replace('data-written_date', 'data-unknown'), 'https://www.kiat.or.kr/'), [])
        self.assertEqual(len(crawl.articles_from_items([item], NOW, source('crawl:kiat'))), 1)

    def test_selenium_list_accepts_minified_html_and_ignores_body_sidebar(self):
        page = '''<nav><a href=/blog/2026/menu/>menu</a></nav><h5 class="mt-0 mb-1"><a href=/blog/2026/release/ class=selenium-link>[가상] Selenium release</a></h5>
                  <p class="mb-2"><small class=text-muted>Friday, October 09, 2026</small></p><div>DO_NOT_COLLECT_BODY</div>'''
        for content in (page, page.replace('href=/blog/2026/release/', 'href="/blog/2026/release/"')):
            [item] = crawl.parse_selenium(content, 'https://www.selenium.dev/blog/')
            self.assertEqual((item['date'], item['url'], item['excerpt']), ('2026-10-09', 'https://www.selenium.dev/blog/2026/release/', None))
            self.assertNotIn('DO_NOT_COLLECT_BODY', str(item))
            self.assertEqual(len(crawl.articles_from_items([item], NOW, source('crawl:selenium'))), 1)
        self.assertEqual(crawl.parse_selenium(page.replace('Friday, October 09, 2026', 'unknown'), 'https://www.selenium.dev/blog/'), [])

    def test_new_channels_collect_with_mock_and_report_zero_items(self):
        pages = {'crawl:kiat': '<a href="javascript:mainContentsGo(\x2790\x27,\x27abc\x27)"><p class="tit">[가상] 공고</p><img data-written_date="2026-10-12"></a>',
                 'crawl:selenium': '<h5><a href=/blog/2026/release/>[가상] 릴리스</a></h5><p><small>Friday, October 09, 2026</small></p>'}
        for method, page in pages.items():
            with self.subTest(method=method), patch.object(crawl, 'allowed', return_value=True), patch.object(crawl, '_get', return_value=(200, 'text/html', page.encode())):
                self.assertEqual(len(crawl.collect(source(method), NOW)), 1)
            with patch.object(crawl, 'allowed', return_value=True), patch.object(crawl, '_get', return_value=(200, 'text/html', b'<html>changed</html>')), self.assertRaises(RssError):
                crawl.collect(source(method), NOW)

    def test_redirect_checks_target_robots_and_https(self):
        robot = crawl.urllib.robotparser.RobotFileParser()
        robot.parse(['User-agent: *', 'Disallow: /blocked'])
        crawl._robots['https://www.example.go.kr'] = robot
        request = urllib.request.Request('https://www.example.go.kr/allowed')
        for target in ('https://www.example.go.kr/blocked', 'http://www.example.go.kr/allowed'):
            with self.subTest(target=target), self.assertRaises(RssError), patch.object(crawl.time, 'sleep') as sleep:
                crawl.SameHostRedirect().redirect_request(request, None, 302, 'Found', {}, target)
            sleep.assert_not_called()

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
