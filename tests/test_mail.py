import copy
from email import message_from_bytes
from email.policy import default
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import unittest
from unittest.mock import patch

import saba.mail as mail
from saba.mail import LOGO_CID, SIGNATURE_CID, build_message, to_mail_html
from saba.newsletter import build_article_view
from saba.schema import validate_articles

ROOT = Path(__file__).resolve().parents[1]
ARTICLES = json.loads((ROOT / "tests/fixtures/analysis_articles.json").read_text(encoding="utf-8"))


class TextParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts, self.skip = [], 0

    def handle_starttag(self, tag, attrs):
        self.skip += tag in ("style", "script", "head")

    def handle_endtag(self, tag):
        self.skip -= tag in ("style", "script", "head")

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)


def visible_text(html: str) -> str:
    parser = TextParser()
    parser.feed(html)
    return " ".join("".join(parser.parts).split())


def body(html: str) -> str:
    return re.sub(r"<style>.*?</style>", "", html, flags=re.S)


class MailTests(unittest.TestCase):
    def setUp(self):
        self.views = [build_article_view(a) for a in validate_articles(copy.deepcopy(ARTICLES))]
        self.html = to_mail_html(self.views, today="2026년 10월 7일 수요일")

    def test_table_layout_without_style_blocks_or_flex(self):
        # 메일 전용 table 템플릿 (D-054): style 블록·flex·grid 없이 640px table 배치와 HTML 속성을 쓴다.
        self.assertNotIn("<link", self.html)
        self.assertNotIn("<script", self.html)
        self.assertNotIn("<style", self.html)
        self.assertIn('<table role="presentation" width="780"', self.html)  # 샘플 폭 (D-056)
        self.assertIn('bgcolor="#111827"', self.html)  # 푸터 (style 무시 앱 대비 HTML 속성)
        styles = " ".join(re.findall(r'style="([^"]*)"', self.html))
        for banned in ("display: flex", "display:flex", "display: grid", "display:grid", "gap:", "grid-template"):
            self.assertNotIn(banned, styles)
        self.assertEqual(mail.flatten_layout('<p style="display: inline-flex;gap: 4px;color: red">'),
                         '<p style="display: inline-block;color: red">')

    def test_all_sections_and_articles_present(self):
        for text in ("오늘의 브리핑", "부서별 주요 이슈", "보안 심층 뉴스", "오늘의 보안 습관", "선정 기준", "업무 범위 확인 중입니다."):
            self.assertIn(text, self.html)
        for view in self.views:
            self.assertIn(view.title, visible_text(self.html))
            self.assertIn(f'name="news-', self.html)
        self.assertEqual(self.html.count("💡 시사점"), len(self.views))

    def test_external_links_only_and_bold_titles(self):
        # 한비로메일은 메일 안 이동 링크를 막고 외부 링크만 동작한다 (D-057 진단). 버튼은 기사 원문으로 연결 (D-058).
        self.assertNotIn('href="#', self.html)
        from saba.newsletter import _mail_department_card
        view = self.views[0]
        view.ai_connections = {"보안사업팀": "가상 연결"}
        card = _mail_department_card("보안사업팀", "🛡️", "security-team", [view], {view.article_id: "news-other-1"})
        url = view.url.replace("&", "&amp;")
        self.assertRegex(card, rf'<a href="{re.escape(url)}" target="_blank" style="[^"]*border:1px solid #d1d5db[^"]*">기사 원문 보기 →</a>')
        for view in self.views:
            self.assertIn(f'<strong>{view.title}</strong>', self.html)

    def test_brief_summary_only(self):
        # 접기·전환이 동작하지 않아 간략 보기만 표시한다 (D-058).
        brief = self.html[self.html.index("오늘의 브리핑"):self.html.index("부서별 주요 이슈")]
        self.assertNotIn("자세히 보기", brief)
        self.assertNotIn("<ul", brief)
        self.assertIn('width="118"', brief)

    def test_brief_counts_match_heading_and_importance_badge(self):
        # 간략 보기 대표 2건 + 외 N건 합계가 제목 건수와 같다 (D-059).
        brief = self.html[self.html.index("오늘의 브리핑"):self.html.index("부서별 주요 이슈")]
        heading = int(re.search(r"(\d+)건</span></h2>", brief).group(1))
        shown = 0
        for row in re.findall(r'width="118".*?</tr>', brief, re.S):
            shown += row.count("<strong>") - 1 + row.count(" · ") + 1  # 대표(굵게) 1 + 나머지 제목
            more = re.search(r"외 (\d+)건", row)
            shown += int(more.group(1)) if more else 0
        self.assertEqual(shown, heading)
        self.assertIn("STE본부", self.html)
        from saba.newsletter import _mail_news_card
        view = self.views[0]
        view.importance = "높음"
        self.assertIn(">긴급</span>", _mail_news_card(view, "x"))

    def test_sample_views_rejected(self):
        sample = build_article_view(validate_articles(copy.deepcopy(ARTICLES))[0], preview_sample={"implications": ["가상"]})
        with self.assertRaises(ValueError):
            to_mail_html([sample])

    def test_browser_preview_uses_image_files(self):
        preview = mail.browser_preview(self.html)
        self.assertNotIn("cid:", body(preview))
        for path in ("../SAMPLE/Codex/v09/LOGO.png", "../sign/sign_img.jpg"):
            self.assertIn(path, preview)
            self.assertTrue((ROOT / "output" / path).resolve().exists())

    def test_logo_and_signature_use_cid(self):
        self.assertRegex(self.html, rf'<img[^>]*src="cid:{LOGO_CID}"[^>]*alt="TBELL SECURITY"')
        self.assertIn(f'src="cid:{SIGNATURE_CID}"', self.html)
        self.assertNotIn("../SAMPLE", body(self.html))
        self.assertNotIn("sign_img.jpg", body(self.html))

    def test_signature_after_footer_and_centered(self):
        self.assertLess(self.html.index("Security · AI · Technology Daily Briefing"), self.html.index("signature-table"))
        # 서명은 780px 본문 안 맨 아래 가운데 (D-056).
        self.assertRegex(self.html, r'<!-- SIGNATURE[^>]*-->\s*<tr><td align="center"[^>]*>\s*<div')
        # 서명이 780px 본문 표 안에 있다: 본문 표가 닫히기 전에 서명 표가 끝난다.
        main_end = self.html.index("</table>", self.html.rindex("signature-table"))
        self.assertLess(self.html.index('width="780"'), self.html.index("signature-table"))
        self.assertGreater(self.html.count("</table>", main_end), 1)

    def test_signature_text_matches_original(self):
        original = visible_text((ROOT / "sign/sign.html").read_text(encoding="utf-8"))
        template = visible_text((ROOT / "templates/email_signature.html").read_text(encoding="utf-8"))
        self.assertEqual(template, original)
        self.assertIn(original, visible_text(self.html))
        for value in ("서창현 선임", "010-3927-4628", "ch.seo@tbell.co.kr", "www.tbell.co.kr"):
            self.assertIn(value, self.html)

    def test_signature_css_matches_original(self):
        template = (ROOT / "templates/email_signature.html").read_text(encoding="utf-8")
        self.assertIn((ROOT / "sign/sign.css").read_text(encoding="utf-8"), template)

    def test_eml_structure_and_no_recipients(self):
        message = build_message(self.html, "[TEST] Security & AI Briefing")
        parsed = message_from_bytes(message.as_bytes(), policy=default)
        self.assertEqual(parsed["Subject"], "[TEST] Security & AI Briefing")
        self.assertIsNone(parsed["To"])
        self.assertIsNone(parsed["From"])
        html_part = parsed.get_body(preferencelist=("html",))
        self.assertIn("Security &amp; AI Briefing", html_part.get_content())
        images = {part["Content-ID"]: part.get_content_type() for part in parsed.walk() if part.get_content_maintype() == "image"}
        self.assertEqual(images, {f"<{LOGO_CID}>": "image/png", f"<{SIGNATURE_CID}>": "image/png"})  # sign_img.jpg 는 실제로 PNG
        self.assertIsNotNone(parsed.get_body(preferencelist=("plain",)))

    def test_no_network_or_send(self):
        self.assertFalse(any(name in dir(mail) for name in ("smtplib", "send", "send_message")))
        with patch("socket.socket.connect", side_effect=AssertionError("네트워크 금지")), \
                patch("smtplib.SMTP", side_effect=AssertionError("발송 금지")):
            build_message(to_mail_html(self.views), "TEST").as_bytes()


if __name__ == "__main__":
    unittest.main()
