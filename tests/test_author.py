"""메일 작성자 설정 (2026-10-16 사용자 요청): 머리말·인사말·서명이 config/author.json 을 따른다."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from saba import author
from saba.mail import signature_body
from saba.newsletter import build_newsletter_html

CHANGED = {**author.DEFAULT, "name": "홍길동", "position": "책임", "team": "가상<팀>", "greeting_team": "",
           "mobile": "010-0000-0000", "email": "virtual@example.com"}


class AuthorTests(unittest.TestCase):
    def test_changed_author_appears_in_header_greeting_and_signature(self):
        with patch.object(author, "load_author", return_value=CHANGED):
            html, signature = build_newsletter_html([]), signature_body()
        self.assertIn("작성자 : 홍길동 책임 · 가상&lt;팀&gt;", html)  # HTML 이스케이프
        self.assertIn("안녕하세요. 가상&lt;팀&gt; 홍길동 책임입니다.", html)  # 인사말 부서를 비우면 부서
        for value in ("홍길동 책임", "010-0000-0000", "mailto:virtual@example.com"):
            self.assertIn(value, signature)
        self.assertNotIn("서창현", html + signature)
        self.assertNotIn("%%AUTHOR", signature)

    def test_validation_and_file_round_trip(self):
        for bad in ({"name": ""}, {"team": ""}, {"email": "no-at"}, {"mobile": "abc"}, {"name": "가" * 21}):
            with self.subTest(bad=bad), self.assertRaises(author.AuthorError):
                author.validate({**author.DEFAULT, **bad})
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "author.json"
            self.assertEqual(author.load_author(path), author.DEFAULT)  # 파일이 없으면 기본값
            author.save_author({**CHANGED, "team": "  가상   팀 "}, path)
            self.assertEqual(author.load_author(path)["team"], "가상 팀")


if __name__ == "__main__":
    unittest.main()
