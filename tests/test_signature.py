"""메일 서명을 관리 화면에서 바꾸기 (2026-10-16 사용자 요청): config/signature.html, 없으면 기본 서명."""
from pathlib import Path
import tempfile
import unittest

from saba import mail


class SignatureTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name) / "signature.html"

    def test_default_when_no_custom_file(self):
        self.assertEqual(mail.signature_body(self.path), mail.signature_body(Path(self.path.parent, "none.html")))
        self.assertIn("010-3927-4628", mail.signature_body(self.path))

    def test_custom_fragment_and_full_document_with_author_tokens(self):
        self.path.write_text('<p class="x">%%AUTHOR_TITLE%% · %%AUTHOR_TEAM%%</p><img src="cid:saba-signature">', encoding="utf-8")
        body = mail.signature_body(self.path)
        self.assertIn("서창현 선임 · SW보안사업팀", body)
        self.assertIn("cid:saba-signature", body)
        self.assertNotIn("010-3927-4628", body)  # 기본 서명이 아니다
        self.path.write_text("<html><head><style>.n{color:red}</style></head><body><b>%%AUTHOR_NAME%%</b></body></html>",
                             encoding="utf-8")
        self.assertEqual(mail.signature_body(self.path), "<style>.n{color:red}</style><b>서창현</b>")

    def test_unsafe_signature_rejected_and_broken_file_falls_back(self):
        for bad in ("", "<script>x()</script>", '<img src=x onerror="x()">', '<a href="javascript:x()">a</a>',
                    "<iframe src=x></iframe>", "a" * (mail.MAX_SIGNATURE + 1)):
            with self.subTest(bad=bad[:20]), self.assertRaises(mail.MailFormatError):
                mail.check_signature(bad)
        self.path.write_text("<script>x()</script>", encoding="utf-8")  # 직접 고쳐 깨진 파일
        with self.assertLogs(level="WARNING"):
            self.assertIn("010-3927-4628", mail.signature_body(self.path))  # 메일은 기본 서명으로 나간다


if __name__ == "__main__":
    unittest.main()
