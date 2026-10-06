import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from datetime import timezone

from pydantic import ValidationError

from saba.__main__ import validate_file
from saba.schema import Article, validate_articles


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "news_valid.json"
EXAMPLES = json.loads(FIXTURE.read_text(encoding="utf-8"))


class SchemaTests(unittest.TestCase):
    def test_minimal_and_optional_articles(self):
        articles = validate_articles(EXAMPLES)
        self.assertEqual(len(articles), 2)
        self.assertIsNone(articles[0].published_at)
        self.assertIsNone(articles[0].extracted_text)
        self.assertIsNone(articles[0].analysis_metadata)
        self.assertEqual(articles[1].summary, EXAMPLES[1]["summary"])
        self.assertEqual(articles[1].evidence_status, EXAMPLES[1]["evidence_status"])
        self.assertEqual(articles[1].official_sources, [])
        self.assertEqual(articles[1].model_dump(mode="json")["analysis_metadata"]["model"], "fictional-model")

    def test_each_required_field_is_required(self):
        for field in EXAMPLES[0]:
            with self.subTest(field=field):
                data = dict(EXAMPLES[0])
                del data[field]
                with self.assertRaises(ValidationError):
                    Article.model_validate(data)

    def test_required_strings_reject_blank(self):
        for field in ("article_id", "original_title", "source_id", "source_name"):
            for value in ("", " \t\n"):
                with self.subTest(field=field, value=value):
                    with self.assertRaises(ValidationError):
                        Article.model_validate(EXAMPLES[0] | {field: value})

    def test_types_are_not_coerced(self):
        cases = [("schema_version", v) for v in ("1", True, 1.0, 2)] + [
            ("article_id", 123), ("original_title", False), ("url", 42),
            ("collection_method", "manual"), ("collected_at", 1720000000),
            ("tags", "test"), ("tags", [1]), ("departments", ("보안사업팀",)),
            ("department_reasons", []), ("summary", 3), ("analysis_metadata", "test"),
        ]
        for field, value in cases:
            with self.subTest(field=field, value=value):
                with self.assertRaises(ValidationError):
                    Article.model_validate(EXAMPLES[0] | {field: value})

    def test_http_urls_only(self):
        for field in ("url", "canonical_url"):
            for value in ("ftp://example.com/test", "file:///test", "example.com", "https://"):
                with self.subTest(field=field, value=value):
                    with self.assertRaises(ValidationError):
                        Article.model_validate(EXAMPLES[0] | {field: value})
        Article.model_validate(EXAMPLES[0] | {"url": "http://example.com/test"})

    def test_datetime_timezone_and_format(self):
        for field in ("collected_at", "published_at", "updated_at"):
            for value in ("2026-10-06T09:00:00", "2026-10-06", "not-a-date", 123):
                with self.subTest(field=field, value=value):
                    with self.assertRaises(ValidationError):
                        Article.model_validate(EXAMPLES[0] | {field: value})
        article = Article.model_validate(EXAMPLES[1])
        self.assertEqual(article.collected_at.tzinfo, timezone.utc)
        self.assertEqual(article.collected_at.hour, 0)
        self.assertEqual(article.published_at.day, 5)
        self.assertEqual(article.published_at.hour, 23)
        self.assertEqual(article.updated_at.tzinfo, timezone.utc)
        self.assertEqual(article.analysis_metadata.analyzed_at.tzinfo, timezone.utc)
        self.assertEqual(article.related_articles[0].published_at.tzinfo, timezone.utc)

    def test_unknown_publication_date(self):
        for data in (EXAMPLES[0], EXAMPLES[0] | {"published_at": None}):
            self.assertIsNone(Article.model_validate(data).published_at)

    def test_unknown_fields(self):
        with self.assertRaises(ValidationError):
            Article.model_validate(EXAMPLES[0] | {"sent": False})

    def test_departments_and_reasons(self):
        cases = [
            {"departments": ["없는부서"]},
            {"departments": ["STE본부"]},
            {"departments": ["보안사업팀", "보안사업팀"]},
            {"department_reasons": {"보안사업팀": "가상 이유"}},
            {"departments": ["경영전략팀"], "department_reasons": {"보안사업팀": "가상 이유"}},
            {"departments": ["보안사업팀"], "department_reasons": {"보안사업팀": " "}},
        ]
        for fields in cases:
            with self.subTest(fields=fields):
                with self.assertRaises(ValidationError):
                    Article.model_validate(EXAMPLES[0] | fields)
        Article.model_validate(EXAMPLES[0] | {"departments": ["보안사업팀", "기술개발연구소"]})

    def test_open_classification_values_and_region(self):
        data = EXAMPLES[0] | {field: "미확정 테스트 분류" for field in ("category", "importance", "evidence_status")}
        Article.model_validate(data)
        for field in ("category", "importance", "evidence_status"):
            with self.subTest(field=field):
                with self.assertRaises(ValidationError):
                    Article.model_validate(data | {field: " "})
        for region in ("국내", "해외", "국제", "미확인"):
            Article.model_validate(EXAMPLES[0] | {"region": region})
        with self.assertRaises(ValidationError):
            Article.model_validate(EXAMPLES[0] | {"region": "unknown"})

    def test_nested_objects(self):
        valid_ref = {"source_name": "가상 출처", "title": "가상 제목", "url": "https://example.com/test"}
        article = Article.model_validate(EXAMPLES[0] | {"official_sources": [valid_ref]})
        self.assertIsNone(article.evidence_status)
        self.assertIsNone(article.official_sources[0].published_at)
        cases = [
            {"official_sources": [valid_ref | {"url": "ftp://example.com"}]},
            {"related_articles": [valid_ref | {"published_at": "2026-10-06T00:00:00"}]},
            {"official_sources": [valid_ref | {"verified": True}]},
            {"evidence_refs": [{"url": "https://example.com", "note": 1}]},
            {"analysis_metadata": {"model": 1}},
            {"analysis_metadata": {"analyzed_at": "2026-10-06T00:00:00"}},
            {"analysis_metadata": {"unknown": "test"}},
        ]
        for fields in cases:
            with self.subTest(fields=fields):
                with self.assertRaises(ValidationError):
                    Article.model_validate(EXAMPLES[0] | fields)

    def test_duplicate_article_ids(self):
        with self.assertRaisesRegex(ValueError, r"\$\[1\]\.article_id"):
            validate_articles([EXAMPLES[0], EXAMPLES[0]])

    def test_batch_shape(self):
        for value in ({}, [], "test", [EXAMPLES[0], {}]):
            with self.subTest(value=value):
                with self.assertRaises(ValidationError):
                    validate_articles(value)

    def test_default_containers_are_independent(self):
        first, second = Article.model_validate(EXAMPLES[0]), Article.model_validate(EXAMPLES[0])
        for field in ("tags", "departments", "key_points", "implications", "official_sources", "related_articles", "evidence_refs"):
            with self.subTest(field=field):
                self.assertIsNot(getattr(first, field), getattr(second, field))
                getattr(first, field).append("test")
                self.assertEqual(getattr(second, field), [])
        first.department_reasons["보안사업팀"] = "test"
        self.assertEqual(second.department_reasons, {})


class CliTests(unittest.TestCase):
    def run_cli(self, *args):
        return subprocess.run(
            [sys.executable, "-X", "utf8", "-m", "saba", *map(str, args)],
            cwd=ROOT, capture_output=True, encoding="utf-8", check=False,
        )

    def test_default_execution(self):
        result = self.run_cli()
        self.assertEqual(result.returncode, 0)
        self.assertIn("SABA 실행을 시작합니다.", result.stderr)
        self.assertIn("외부 연결과 실제 메일 발송 기능은 없으며", result.stderr)
        self.assertIn("정상 종료", result.stderr)

    def test_valid_fixture(self):
        result = self.run_cli("--validate-json", FIXTURE)
        self.assertEqual(result.returncode, 0)
        self.assertIn("유효한 기사 2건", result.stderr)
        self.assertIn("수집·저장·분석·발송은 수행하지 않았습니다", result.stderr)

    def test_error_inputs_and_cleanup(self):
        invalid = copy.deepcopy(EXAMPLES)
        invalid[1]["original_title"] = " "
        invalid[1]["extracted_text"] = "DO_NOT_LOG_RAW_BODY"
        cases = [
            ("malformed", b'{"DO_NOT_LOG_RAW_BODY":', "JSON / 1행"),
            ("encoding", b'\xff', "인코딩"),
            ("object", b'{}', "최상위 구조"),
            ("empty", b'[]', "빈 배열"),
            ("schema", json.dumps(invalid).encode(), "$[1].original_title"),
            ("duplicate", json.dumps([EXAMPLES[0], EXAMPLES[0]]).encode(), "$[1].article_id"),
        ]
        with tempfile.TemporaryDirectory(prefix="saba-cli-", dir=ROOT / ".venv") as directory:
            for name, payload, expected in cases:
                with self.subTest(name=name):
                    path = Path(directory) / f"{name}.json"
                    path.write_bytes(payload)
                    result = self.run_cli("--validate-json", path)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn(expected, result.stderr)
                    self.assertNotIn("DO_NOT_LOG_RAW_BODY", result.stderr + result.stdout)
                    self.assertNotIn("검증 성공", result.stderr)
            missing = self.run_cli("--validate-json", Path(directory) / "missing.json")
            self.assertNotEqual(missing.returncode, 0)
            self.assertIn("FileNotFoundError", missing.stderr)
        self.assertFalse(Path(directory).exists())

    def test_read_permission_error(self):
        with patch.object(Path, "read_text", side_effect=PermissionError(13, "denied")):
            with self.assertLogs(level="ERROR") as logs:
                self.assertEqual(validate_file(Path("test.json")), 1)
        self.assertIn("PermissionError", logs.output[0])


if __name__ == "__main__":
    unittest.main()
