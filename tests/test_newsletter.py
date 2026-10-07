import copy
import hashlib
import json
import re
from pathlib import Path
import unittest

from saba.analysis import AnalysisResult
from saba.newsletter import build_article_view, build_newsletter_html
from saba.schema import validate_articles

ROOT = Path(__file__).resolve().parents[1]
ARTICLES_PATH = ROOT / "tests" / "fixtures" / "analysis_articles.json"
RESULTS_PATH = ROOT / "tests" / "fixtures" / "analysis_valid.json"


class NewsletterTests(unittest.TestCase):
    def setUp(self):
        article_data = json.loads(ARTICLES_PATH.read_text(encoding="utf-8"))
        result_data = json.loads(RESULTS_PATH.read_text(encoding="utf-8"))
        self.articles = validate_articles(copy.deepcopy(article_data))
        self.analysis_results = [AnalysisResult.model_validate(item) for item in copy.deepcopy(result_data)]

    def test_normal_article_html_generation(self):
        view = build_article_view(self.articles[0])
        html = build_newsletter_html([view])
        self.assertIsInstance(html, str)
        self.assertTrue(html)
        self.assertIn("[가상] 테스트 도구 새 버전 안내", html)
        self.assertIn("가상 문서실", html)

    def test_article_with_analysis_html_generation(self):
        view = build_article_view(self.articles[0], self.analysis_results[0])
        html = build_newsletter_html([view])
        self.assertIn("[가상] 테스트 도구 새 버전", html)
        self.assertNotIn("[가상] 테스트 도구 새 버전 안내</a>", html)
        self.assertIn("가상 문서실에 따르면 가상 도구 새 버전이 공개됐고 문서 검색 기능이 추가됐습니다.", html)

    def test_no_analysis_html_succeeds(self):
        html = build_newsletter_html([build_article_view(article) for article in self.articles])
        self.assertIsInstance(html, str)
        self.assertNotIn("[가상] 테스트 도구 새 버전</a>", html)
        self.assertNotIn("가상 문서실에 따르면 가상 도구 새 버전이 공개됐고 문서 검색 기능이 추가됐습니다.", html)

    def test_no_excerpt_succeeds(self):
        view = build_article_view(self.articles[1])
        self.assertIsNone(view.excerpt)
        html = build_newsletter_html([view])
        self.assertIsInstance(html, str)

    def test_no_published_at_succeeds(self):
        view = build_article_view(self.articles[1])
        self.assertEqual(view.date_label, "수집일")
        html = build_newsletter_html([view])
        self.assertIsInstance(html, str)

    def test_empty_article_list(self):
        html = build_newsletter_html([])
        self.assertIn("수집된 기사가 없습니다", html)

    def test_special_chars_html_escaped(self):
        article = self.articles[0].model_copy(update={"original_title": '<script>alert(1)</script>'})
        view = build_article_view(article)
        html = build_newsletter_html([view])
        self.assertNotIn("<script>alert(1)</script>", html)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", html)

    def test_url_in_output(self):
        view = build_article_view(self.articles[0])
        html = build_newsletter_html([view])
        self.assertIn(str(view.url), html)

    def test_source_name_in_output(self):
        view = build_article_view(self.articles[0])
        html = build_newsletter_html([view])
        self.assertIn("가상 문서실", html)

    def test_ai_and_source_data_distinction(self):
        with_analysis = build_article_view(self.articles[0], self.analysis_results[0])
        without_analysis = build_article_view(self.articles[0])
        self.assertEqual(with_analysis.title, self.analysis_results[0].newsletter_title)
        self.assertEqual(without_analysis.title, self.articles[0].original_title)
        self.assertNotEqual(with_analysis.title, without_analysis.title)

    def test_no_fake_ai_data_without_analysis(self):
        view = build_article_view(self.articles[0])
        html = build_newsletter_html([view])
        self.assertIsNone(view.importance)
        self.assertIsNone(view.summary)
        self.assertEqual(view.key_points, [])
        self.assertFalse(view.has_full_analysis)
        self.assertNotIn(self.analysis_results[0].summary or "", html)
        self.assertNotIn(f">{self.analysis_results[0].newsletter_title}</a>", html)

    def test_protected_originals_not_modified(self):
        expected = {
            ROOT / "SAMPLE" / "Codex" / "v09" / "layout_review_v9.html": "4465E25461E142882297356D1C2804036497A09E3CBA1A3E550367F60013311A",
            ROOT / "SAMPLE" / "Codex" / "v09" / "style_review_v9.css": "C706CE6127E4539ADF36F49F881FC7D5F516EB9748EA6A477A8D6B0F227BE5FC",
            ROOT / "SAMPLE" / "Codex" / "v09" / "LOGO.png": "0CD1B23E732C61E2574436306CBD16B98C05F2BC5EC28BC9C80679E94E9F0C4E",
            ROOT / "sign" / "sign.html": "983ACC84E58B87449E62F49FC13C322103C81D674EDA62D5D19A4FC4E85A1F4B",
            ROOT / "sign" / "sign.css": "33AAC2A521E8A2F53D018CD98A5019B00829F0779FD1CA93D41DA1EE05933BF7",
            ROOT / "sign" / "sign_img.jpg": "D2F2A5BFEDBD602894CDAE61DAF9610E3EAC4BCE119264437373EBF3484AF3F9",
        }
        for path, digest in expected.items():
            with self.subTest(path=path):
                actual = hashlib.sha256(path.read_bytes()).hexdigest().upper()
                self.assertEqual(actual, digest)

    def test_author_and_original_greeting(self):
        html = build_newsletter_html([])
        self.assertIn("서창현 선임 · SW보안사업팀", html)
        self.assertIn("안녕하세요. 보안사업팀 서창현 선임입니다.", html)
        self.assertIn("감사합니다.", html)

    def test_empty_regions_and_original_briefing_groups_remain(self):
        html = build_newsletter_html([])
        for label in ("국내 보안", "해외 보안", "AI & Tech", "일정", "핫이슈", "보안시장 동향", "기업 소식", "경제 지표"):
            self.assertIn(label, html)
        self.assertIn("간략 보기", html)
        self.assertIn("자세히 보기", html)

    def test_region_is_not_inferred_from_source(self):
        from saba.newsletter import article_section
        for region, expected in (("국내", "domestic"), ("해외", "overseas"), (None, "other")):
            article = self.articles[0].model_copy(update={"region": region})
            self.assertEqual(article_section(build_article_view(article)), expected)

    def test_sources_and_related_article_are_escaped(self):
        data = self.articles[0].model_dump(mode="json")
        data["related_articles"] = [{"source_name": "가상 참고", "title": '<참고 & 문서>',
                                     "url": "https://example.com/related?a=1&b=2"}]
        article = validate_articles([data])[0]
        html = build_newsletter_html([build_article_view(article)])
        self.assertIn("출처 · 관련 기사", html)
        self.assertIn(str(article.url).replace("&", "&amp;"), html)
        self.assertIn("&lt;참고 &amp; 문서&gt;", html)
        self.assertIn("https://example.com/related?a=1&amp;b=2", html)

    def test_sample_insight_and_work_connection_are_preview_only(self):
        view = build_article_view(self.articles[0], self.analysis_results[0], preview_sample={
            "implications": ["가상 시사점 <검증>"], "connections": {"보안사업팀": "가상 연결 & 검증"}})
        with self.assertRaises(ValueError):
            build_newsletter_html([view])
        html = build_newsletter_html([view], preview_mode=True)
        self.assertIn("시사점", html)
        self.assertIn("우리 업무와의 연결", html)
        self.assertIn("SAMPLE/MOCK: 가상 시사점 &lt;검증&gt;", html)
        self.assertIn("가상 연결 &amp; 검증", html)
        self.assertIn("관련 이슈 1건", html)

    def test_fallback_has_structure_but_no_fabricated_analysis(self):
        html = build_newsletter_html([build_article_view(self.articles[0])])
        self.assertIn("우리 업무와의 연결", html)
        self.assertIn("분석 정보가 없습니다.", html)
        self.assertIn("검토된 업무 연결 정보가 없습니다.", html)
        self.assertNotIn("SAMPLE/MOCK:", html)
        self.assertNotIn("핵심 사실", html)

    def test_key_points_are_not_mislabeled_as_implications(self):
        view = build_article_view(self.articles[0], self.analysis_results[0])
        html = build_newsletter_html([view])
        self.assertIn("핵심 사실", html)
        self.assertEqual(view.sample_implications, [])

    def test_template_is_the_renderer_source(self):
        template = (ROOT / "templates/newsletter.html").read_text(encoding="utf-8")
        self.assertIn("{deep_news}", template)
        self.assertIn("{department_cards}", template)
        self.assertIn("서창현 선임 · SW보안사업팀", template)

    def test_sample_group_validation_and_input_preservation(self):
        article = self.articles[0]
        before = article.model_dump_json()
        with self.assertRaises(ValueError):
            build_article_view(article, preview_sample={"brief_group": "invalid"})
        view = build_article_view(article, preview_sample={"brief_group": "economy"})
        html = build_newsletter_html([view], preview_mode=True)
        self.assertIn("경제 지표", html)
        self.assertEqual(article.model_dump_json(), before)

    def test_rendering_never_uses_network_or_database(self):
        from unittest.mock import patch
        with patch("socket.create_connection", side_effect=AssertionError("network")), \
             patch("sqlite3.connect", side_effect=AssertionError("database")):
            html = build_newsletter_html([build_article_view(self.articles[0])])
        self.assertIn("출처 · 관련 기사", html)

    def test_utf8_preview_label_roundtrip_and_charset(self):
        html = build_newsletter_html([], preview_mode=True)
        restored = html.encode("utf-8").decode("utf-8")
        self.assertIn("SAMPLE/MOCK 미리보기", restored)
        self.assertIn("서창현 선임 · SW보안사업팀", restored)
        self.assertIn("감사합니다.", restored)
        self.assertIn('charset="utf-8"', restored)
        self.assertNotIn("SAMPLE/MOCK Preview ?", restored)
        self.assertNotIn("\ufffd", restored)
        header = re.search(r'<header\b.*?</header>', restored, re.S)[0]
        self.assertNotIn("?", header)  # 원본 피드백의 정상 질문 문구는 보존한다.

    def test_header_dom_matches_original_and_greeting_is_preserved(self):
        from html.parser import HTMLParser
        class Structure(HTMLParser):
            def __init__(self):
                super().__init__()
                self.tags = []
            def handle_starttag(self, tag, attrs):
                self.tags.append((tag, dict(attrs).get("class")))
            def handle_endtag(self, tag):
                self.tags.append(("/" + tag, None))
        original = (ROOT / "SAMPLE/Codex/v09/layout_review_v9.html").read_text(encoding="utf-8")
        rendered = build_newsletter_html([])
        structures = []
        for document in (original, rendered):
            parser = Structure()
            parser.feed(re.search(r'<header\b.*?</header>', document, re.S)[0])
            structures.append(parser.tags)
        self.assertEqual(*structures)
        greeting = re.search(r'<section class="greeting">.*?</section>', original, re.S)[0]
        self.assertIn(greeting, rendered)

    def test_department_limit_three_preserves_order_and_input(self):
        views = [build_article_view(self.articles[0].model_copy(update={"article_id": f"limit-{i}",
                 "original_title": f"limit-title-{i}"}), preview_sample={"connections": {
                 name: "가상 배정" for name in ("경영전략팀", "기술개발연구소", "보안사업팀", "STE본")}})
                 for i in range(5)]
        before = copy.deepcopy(views)
        html = build_newsletter_html(views, preview_mode=True)
        cards = re.findall(r'<article class="department-card .*?</article>', html, re.S)
        self.assertEqual(len(cards), 4)
        for card in cards:
            self.assertEqual(card.count('class="department-news-item"'), 3)
            self.assertIn("관련 이슈 3건", card)
            self.assertLess(card.index("limit-title-0"), card.index("limit-title-1"))
            self.assertLess(card.index("limit-title-1"), card.index("limit-title-2"))
            self.assertNotIn("limit-title-3", card)
            self.assertNotIn("limit-title-4", card)
            self.assertIn('class="card-meta-row"', card)
            self.assertIn('class="card-actions"', card)
        self.assertEqual(views, before)
        self.assertIn("limit-title-4", html)  # 상세 목록은 새 상한을 적용하지 않는다.

    def test_preview_label_does_not_add_a_top_level_warning(self):
        html = build_newsletter_html([], preview_mode=True)
        header = re.search(r'<header\b.*?</header>', html, re.S)[0]
        self.assertIn("SAMPLE/MOCK 미리보기", header)
        self.assertNotIn("SAMPLE/MOCK 미리보기", build_newsletter_html([]))
        between = html.split('</section>', 1)[1].split('<section', 1)[0]
        self.assertNotIn('<p', between)

    def test_summary_does_not_duplicate_source_excerpt(self):
        view = build_article_view(self.articles[0], self.analysis_results[0])
        html = build_newsletter_html([view])
        card = re.search(r'<article class="news-card".*?</article>', html, re.S)[0]
        self.assertIn(self.analysis_results[0].summary, card)
        self.assertNotIn('<div class="news-meta">', card)


if __name__ == "__main__":
    unittest.main()
