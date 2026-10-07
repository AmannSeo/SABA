import copy
import hashlib
import json
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
        }
        for path, digest in expected.items():
            with self.subTest(path=path):
                actual = hashlib.sha256(path.read_bytes()).hexdigest().upper()
                self.assertEqual(actual, digest)


if __name__ == "__main__":
    unittest.main()
