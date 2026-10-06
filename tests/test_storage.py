from contextlib import closing
import copy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from pydantic import ValidationError

from saba.schema import Article, validate_articles
from saba.storage import (
    CREATE_TABLE, DEFAULT_DB, StorageError, get_article, list_articles,
    read_connection, save_articles,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "news_valid.json"
EXAMPLES = json.loads(FIXTURE.read_text(encoding="utf-8"))


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="saba-storage-", dir=ROOT / ".venv")
        self.addCleanup(self.temporary.cleanup)
        self.folder = Path(self.temporary.name)
        self.db = self.folder / "nested" / "articles.db"
        self.articles = validate_articles(EXAMPLES)

    def test_roundtrip_after_reconnection(self):
        self.assertEqual(save_articles(self.db, self.articles), (2, 0))
        restored = list_articles(self.db)
        self.assertEqual(len(restored), 2)
        for original in self.articles:
            with self.subTest(article_id=original.article_id):
                article = get_article(self.db, original.article_id)
                self.assertEqual(article.model_dump(mode="json"), original.model_dump(mode="json"))
                self.assertEqual(Article.model_validate_json(article.model_dump_json()), original)
        minimal = get_article(self.db, self.articles[0].article_id)
        self.assertIsNone(minimal.published_at)
        self.assertEqual(minimal.collected_at.tzinfo, timezone.utc)
        with closing(sqlite3.connect(self.db)) as connection:
            published, collected, payload, stored = connection.execute(
                "SELECT published_at, collected_at, article_json, stored_at FROM articles WHERE article_id = ?",
                (minimal.article_id,),
            ).fetchone()
        self.assertIsNone(published)
        self.assertEqual(collected, "2026-10-06T00:00:00+00:00")
        self.assertIn("가상 테스트", payload)
        self.assertIsNone(json.loads(payload)["published_at"])
        self.assertEqual(datetime.fromisoformat(stored).utcoffset().total_seconds(), 0)

    def test_same_normalized_data_is_skipped(self):
        save_articles(self.db, self.articles)
        before = self.db.read_bytes()
        equivalent = copy.deepcopy(EXAMPLES)
        equivalent[0]["collected_at"] = "2026-10-06T00:00:00Z"
        equivalent[0]["published_at"] = None
        equivalent[0]["tags"] = []
        equivalent[1]["department_reasons"] = dict(reversed(list(equivalent[1]["department_reasons"].items())))
        self.assertEqual(save_articles(self.db, validate_articles(equivalent)), (0, 2))
        self.assertEqual(len(list_articles(self.db)), 2)
        self.assertEqual(self.db.read_bytes(), before)

    def test_conflict_rolls_back_prior_new_insert(self):
        save_articles(self.db, self.articles)
        before = self.db.read_bytes()
        new = EXAMPLES[0] | {"article_id": "new-before-conflict"}
        conflicting = EXAMPLES[1] | {"summary": "가상 테스트 변경값"}
        with self.assertRaisesRegex(StorageError, r"\$\[1\]\.article_id"):
            save_articles(self.db, validate_articles([new, conflicting]))
        self.assertEqual(self.db.read_bytes(), before)
        self.assertEqual(len(list_articles(self.db)), 2)
        self.assertEqual(get_article(self.db, self.articles[1].article_id), self.articles[1])
        with self.assertRaises(StorageError):
            get_article(self.db, "new-before-conflict")

    def test_mid_insert_sqlite_failure_rolls_back(self):
        save_articles(self.db, self.articles)
        before = self.db.read_bytes()
        real_connect = sqlite3.connect
        inserted_ids = []

        class FailingConnection(sqlite3.Connection):
            def execute(self, sql, parameters=()):
                if sql.lstrip().startswith("INSERT"):
                    inserted_ids.append(parameters[0])
                    if len(inserted_ids) == 2:
                        raise sqlite3.OperationalError("test insertion failure")
                return super().execute(sql, parameters)

        def failing_connect(*args, **kwargs):
            return real_connect(*args, **kwargs, factory=FailingConnection)

        new = [EXAMPLES[0] | {"article_id": "new-1"}, EXAMPLES[0] | {"article_id": "new-2"}]
        with patch("saba.storage.sqlite3.connect", side_effect=failing_connect):
            with self.assertRaises(sqlite3.OperationalError):
                save_articles(self.db, validate_articles(new))
        self.assertEqual(inserted_ids, ["new-1", "new-2"])
        self.assertEqual(self.db.read_bytes(), before)

    def test_invalid_models_are_rejected_before_db_creation(self):
        self.articles[1].original_title = " "
        with self.assertRaises(ValidationError):
            save_articles(self.db, self.articles)
        self.assertFalse(self.db.exists())
        self.assertFalse(self.db.parent.exists())

    def test_absent_db_queries_create_nothing(self):
        for query in (lambda: list_articles(self.db), lambda: get_article(self.db, "missing")):
            with self.subTest(query=query):
                with self.assertRaisesRegex(StorageError, "DB 파일이 없습니다"):
                    query()
        self.assertFalse(self.db.exists())
        self.assertFalse(self.db.parent.exists())

    def test_missing_article_and_empty_database(self):
        self.db.parent.mkdir()
        with closing(sqlite3.connect(self.db)) as connection:
            connection.execute(CREATE_TABLE)
        self.assertEqual(list_articles(self.db), [])
        with self.assertRaisesRegex(StorageError, "해당 기사가 DB에 없습니다"):
            get_article(self.db, "missing")

    def test_queries_are_readonly_and_do_not_change_db(self):
        save_articles(self.db, self.articles)
        digest = hashlib.sha256(self.db.read_bytes()).digest()
        list_articles(self.db)
        get_article(self.db, self.articles[0].article_id)
        with closing(read_connection(self.db)) as connection:
            with self.assertRaises(sqlite3.OperationalError):
                connection.execute("DELETE FROM articles")
        self.assertEqual(hashlib.sha256(self.db.read_bytes()).digest(), digest)

    def test_sql_input_is_treated_as_data(self):
        article_id = "test'); DROP TABLE articles; --"
        article = Article.model_validate(EXAMPLES[0] | {"article_id": article_id, "original_title": "가상 ' SQL -- 테스트"})
        save_articles(self.db, [article])
        self.assertEqual(get_article(self.db, article_id), article)
        self.assertEqual(len(list_articles(self.db)), 1)
        with self.assertRaises(StorageError):
            get_article(self.db, "' OR 1=1 --")

    def test_unexpected_existing_structure_is_preserved(self):
        self.db.parent.mkdir()
        with closing(sqlite3.connect(self.db)) as connection:
            connection.execute("CREATE TABLE unrelated (value TEXT)")
        before = self.db.read_bytes()
        for action in (lambda: save_articles(self.db, self.articles), lambda: list_articles(self.db)):
            with self.subTest(action=action):
                with self.assertRaisesRegex(StorageError, "DB 구조가 예상과 다릅니다"):
                    action()
        self.assertEqual(self.db.read_bytes(), before)

    def test_wrong_article_columns_are_rejected(self):
        self.db.parent.mkdir()
        with closing(sqlite3.connect(self.db)) as connection:
            connection.execute("CREATE TABLE articles (article_id TEXT PRIMARY KEY, article_json TEXT)")
        before = self.db.read_bytes()
        with self.assertRaises(StorageError):
            save_articles(self.db, self.articles)
        self.assertEqual(self.db.read_bytes(), before)

    def test_corrupt_article_json_is_reported_without_body(self):
        save_articles(self.db, self.articles)
        with closing(sqlite3.connect(self.db)) as connection:
            with connection:
                connection.execute("UPDATE articles SET article_json = ?", ("DO_NOT_LOG_RAW_BODY",))
        with self.assertRaises(StorageError) as error:
            list_articles(self.db)
        self.assertNotIn("DO_NOT_LOG_RAW_BODY", str(error.exception))

    def test_extra_constraint_is_not_silently_accepted(self):
        self.db.parent.mkdir()
        different = CREATE_TABLE.replace("source_id TEXT NOT NULL", "source_id TEXT NOT NULL UNIQUE")
        with closing(sqlite3.connect(self.db)) as connection:
            connection.execute(different)
        before = self.db.read_bytes()
        with self.assertRaisesRegex(StorageError, "DB 구조가 예상과 다릅니다"):
            save_articles(self.db, self.articles)
        self.assertEqual(self.db.read_bytes(), before)

    def test_official_sources_are_preserved(self):
        data = copy.deepcopy(EXAMPLES[1])
        data["official_sources"] = copy.deepcopy(data["related_articles"])
        article = Article.model_validate(data)
        save_articles(self.db, [article])
        self.assertEqual(get_article(self.db, article.article_id), article)


class StorageCliTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="saba-storage-cli-", dir=ROOT / ".venv")
        self.addCleanup(self.temporary.cleanup)
        self.folder = Path(self.temporary.name)
        self.db = self.folder / "custom" / "cli.db"

    def run_cli(self, *args, cwd=ROOT):
        return subprocess.run(
            [sys.executable, "-X", "utf8", "-m", "saba", *map(str, args)],
            cwd=cwd, capture_output=True, encoding="utf-8", check=False,
        )

    def test_import_reimport_and_separate_process_queries(self):
        first = self.run_cli("--import-json", FIXTURE, "--db", self.db)
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertIn("신규 2건 · 동일 데이터 0건 생략", first.stderr)
        second = self.run_cli("--import-json", FIXTURE, "--db", self.db)
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertIn("신규 0건 · 동일 데이터 2건 생략", second.stderr)
        listing = self.run_cli("--list-articles", "--db", self.db)
        self.assertEqual(listing.returncode, 0, listing.stderr)
        self.assertIn("저장 기사 2건", listing.stdout)
        self.assertIn("미확인", listing.stdout)
        self.assertNotIn(EXAMPLES[1]["extracted_text"], listing.stdout + listing.stderr)
        detail = self.run_cli("--show-article", EXAMPLES[1]["article_id"], "--db", self.db)
        self.assertEqual(detail.returncode, 0, detail.stderr)
        self.assertEqual(Article.model_validate_json(detail.stdout), validate_articles(EXAMPLES)[1])
        self.assertNotIn(EXAMPLES[1]["extracted_text"], detail.stderr)
        missing = self.run_cli("--show-article", "missing", "--db", self.db)
        self.assertEqual(missing.returncode, 1)

    def test_invalid_import_creates_no_db(self):
        for payload in ("{", json.dumps([EXAMPLES[0], EXAMPLES[1] | {"original_title": " "}])):
            with self.subTest(payload=payload):
                path = self.folder / "invalid.json"
                path.write_text(payload, encoding="utf-8")
                result = self.run_cli("--import-json", path, "--db", self.db)
                self.assertEqual(result.returncode, 1)
                self.assertFalse(self.db.exists())
                self.assertFalse(self.db.parent.exists())

    def test_invalid_import_preserves_existing_db(self):
        self.run_cli("--import-json", FIXTURE, "--db", self.db)
        before = self.db.read_bytes()
        path = self.folder / "invalid.json"
        path.write_text("[{}]", encoding="utf-8")
        self.assertEqual(self.run_cli("--import-json", path, "--db", self.db).returncode, 1)
        self.assertEqual(self.db.read_bytes(), before)

    def test_cli_conflict_rolls_back(self):
        self.run_cli("--import-json", FIXTURE, "--db", self.db)
        before = self.db.read_bytes()
        data = [EXAMPLES[0] | {"article_id": "new-before-conflict"}, EXAMPLES[1] | {"summary": "DO_NOT_LOG_RAW_BODY"}]
        path = self.folder / "conflict.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        result = self.run_cli("--import-json", path, "--db", self.db)
        self.assertEqual(result.returncode, 1)
        self.assertIn("Rollback", result.stderr)
        self.assertNotIn("DO_NOT_LOG_RAW_BODY", result.stderr + result.stdout)
        self.assertEqual(self.db.read_bytes(), before)

    def test_absent_db_cli_queries(self):
        for args in (("--list-articles",), ("--show-article", "missing")):
            with self.subTest(args=args):
                result = self.run_cli(*args, "--db", self.db)
                self.assertEqual(result.returncode, 1)
                self.assertIn("DB 파일이 없습니다", result.stderr)
        self.assertFalse(self.db.parent.exists())

    def test_option_combinations(self):
        cases = [
            ("--db", self.db),
            ("--validate-json", FIXTURE, "--db", self.db),
            ("--validate-json", FIXTURE, "--import-json", FIXTURE),
            ("--import-json", FIXTURE, "--list-articles"),
            ("--list-articles", "--show-article", "id"),
            ("--show-article", " "),
        ]
        for args in cases:
            with self.subTest(args=args):
                self.assertEqual(self.run_cli(*args).returncode, 2)
        self.assertFalse(self.db.exists())

    def test_default_and_validation_do_not_touch_db(self):
        self.assertEqual(DEFAULT_DB, ROOT / "data" / "saba.db")
        alternate = self.folder / "default.db"
        with patch("saba.__main__.DEFAULT_DB", alternate):
            from saba.__main__ import main
            for args in (("saba",), ("saba", "--validate-json", str(FIXTURE))):
                with self.subTest(args=args), patch.object(sys, "argv", args):
                    self.assertEqual(main(), 0)
        self.assertFalse(alternate.exists())

    def test_default_path_is_independent_of_working_directory(self):
        result = subprocess.run(
            [sys.executable, "-X", "utf8", "-c", "from saba.storage import DEFAULT_DB; print(DEFAULT_DB)"],
            cwd=self.folder, capture_output=True, encoding="utf-8", check=False,
        )
        self.assertEqual(result.returncode, 0)
        self.assertEqual(Path(result.stdout.strip()), ROOT / "data" / "saba.db")

    def test_corrupt_database_is_safe_error(self):
        self.db.parent.mkdir()
        self.db.write_bytes(b"not-a-sqlite-database DO_NOT_LOG_RAW_BODY")
        before = self.db.read_bytes()
        for args in (("--list-articles",), ("--import-json", FIXTURE)):
            with self.subTest(args=args):
                result = self.run_cli(*args, "--db", self.db)
                self.assertEqual(result.returncode, 1)
                self.assertIn("SQLITE_NOTADB", result.stderr)
                self.assertNotIn("DO_NOT_LOG_RAW_BODY", result.stderr)
        self.assertEqual(self.db.read_bytes(), before)

    def test_locked_database_is_safe_error(self):
        save_articles(self.db, validate_articles(EXAMPLES))
        with closing(sqlite3.connect(self.db)) as connection:
            connection.execute("BEGIN EXCLUSIVE")
            result = self.run_cli("--import-json", FIXTURE, "--db", self.db)
            connection.rollback()
        self.assertEqual(result.returncode, 1)
        self.assertIn("SQLITE_BUSY", result.stderr)
        self.assertNotIn("Traceback", result.stderr)


if __name__ == "__main__":
    unittest.main()
