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
from saba.mail import LOGO_CID, SIGNATURE_CID, MailFormatError, build_message, to_mail_html
from saba.newsletter import build_article_view, build_newsletter_html
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
        views = [build_article_view(a) for a in validate_articles(copy.deepcopy(ARTICLES))]
        self.newsletter = build_newsletter_html(views, today="2026년 10월 7일 수요일")
        self.html = to_mail_html(self.newsletter)

    def test_external_css_and_script_removed_and_css_embedded(self):
        self.assertNotIn("<link", self.html)
        self.assertNotIn("<script", self.html)
        self.assertIn((ROOT / "SAMPLE/Codex/v09/style_review_v9.css").read_text(encoding="utf-8")[:200], self.html)

    def test_css_view_switch_kept_without_script(self):
        content = body(self.html)
        self.assertNotIn("<script", content)
        for kept in ('id="brief-view-summary" checked', 'for="brief-view-detail"', 'class="brief-summary-view"', 'class="brief-detail-view"'):
            self.assertIn(kept, content)
        self.assertIn("#brief-view-detail:checked ~ .brief-detail-view", self.html)

    def test_browser_preview_uses_image_files(self):
        preview = mail.browser_preview(self.html)
        self.assertNotIn("cid:", body(preview))
        for path in ("../SAMPLE/Codex/v09/LOGO.png", "../sign/sign_img.jpg"):
            self.assertIn(path, preview)
            self.assertTrue((ROOT / "output" / path).resolve().exists())

    def test_logo_and_signature_use_cid(self):
        self.assertIn(f'<img class="header-logo" src="cid:{LOGO_CID}"', self.html)
        self.assertIn(f'src="cid:{SIGNATURE_CID}"', self.html)
        self.assertNotIn("../SAMPLE", body(self.html))
        self.assertNotIn("sign_img.jpg", body(self.html))

    def test_newsletter_text_preserved(self):
        self.assertIn(visible_text(self.newsletter), visible_text(self.html))

    def test_signature_inside_newsletter_width(self):
        content = body(self.html)
        self.assertLess(content.index('<div class="mail-signature">'), content.index("</main>"))
        self.assertIn(".mail-signature .signature-table", self.html)

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

    def test_unexpected_structure_rejected(self):
        with self.assertRaises(MailFormatError):
            to_mail_html("<html><body>no template</body></html>")

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
            build_message(to_mail_html(self.newsletter), "TEST").as_bytes()


if __name__ == "__main__":
    unittest.main()
