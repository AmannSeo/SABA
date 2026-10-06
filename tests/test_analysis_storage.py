from contextlib import closing
import copy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from pydantic import ValidationError

from saba.analysis import AnalysisError, InputSnapshot, input_payload, json_hash
from saba.analysis_storage import (
    CREATE_TABLE, DEFAULT_ANALYSIS_DB, get_analysis, list_analyses, save_analysis,
)
from saba.schema import validate_articles
from saba.storage import StorageError, save_articles

ROOT = Path(__file__).resolve().parents[1]
ARTICLES = ROOT / "tests/fixtures/analysis_articles.json"
RESULTS = ROOT / "tests/fixtures/analysis_valid.json"
ARTICLE_DATA = json.loads(ARTICLES.read_text(encoding="utf-8"))
RESULT_DATA = json.loads(RESULTS.read_text(encoding="utf-8"))


class AnalysisStorageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="saba-analysis-storage-", dir=ROOT / ".venv")
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.article_db = self.folder / "articles.db"
        self.db = self.folder / "nested" / "analysis.db"
        self.articles = validate_articles(copy.deepcopy(ARTICLE_DATA))
        self.results = copy.deepcopy(RESULT_DATA)
        save_articles(self.article_db, self.articles)
        self.article_before = self.article_db.read_bytes()

    def cli(self, *args):
        return subprocess.run([sys.executable, "-X", "utf8", "-m", "saba", *map(str, args)], cwd=self.folder, capture_output=True, encoding="utf-8")

    def import_cli(self, path=RESULTS):
        return self.cli("--import-analysis", path, "--db", self.article_db, "--analysis-db", self.db)

    def test_three_statuses_roundtrip_snapshot_and_article_unchanged(self):
        self.assertEqual(save_analysis(self.article_db, self.db, self.results), (3, 0))
        records = list_analyses(self.db)
        self.assertEqual(len(records), 3)
        for result in self.results:
            record = get_analysis(self.db, json_hash(result))
            self.assertEqual(record["result"], result)
            original = next(a for a in self.articles if a.article_id == result["article_id"])
            self.assertEqual(record["input"], input_payload(original))
            self.assertNotIn("collected_at", record["input"])
            self.assertNotIn("summary", record["input"])
            self.assertEqual(datetime.fromisoformat(record["stored_at"]).utcoffset().total_seconds(), 0)
        self.assertIsNone(get_analysis(self.db, json_hash(self.results[1]))["input"]["published_at"])
        self.assertEqual(self.article_db.read_bytes(), self.article_before)

    def test_identical_reimport_preserves_bytes_and_stored_at(self):
        save_analysis(self.article_db, self.db, self.results)
        before = self.db.read_bytes()
        records = list_analyses(self.db)
        self.assertEqual(save_analysis(self.article_db, self.db, self.results), (0, 3))
        self.assertEqual(list_analyses(self.db), records)
        self.assertEqual(self.db.read_bytes(), before)

    def test_same_input_different_result_adds_history(self):
        save_analysis(self.article_db, self.db, self.results)
        old = get_analysis(self.db, json_hash(self.results[0]))
        changed = self.results[0] | {"reason": "다른 합성 검토 이유"}
        self.assertEqual(save_analysis(self.article_db, self.db, [changed]), (1, 0))
        self.assertEqual(len(list_analyses(self.db)), 4)
        self.assertEqual(get_analysis(self.db, json_hash(self.results[0])), old)

    def test_missing_article_or_db_creates_no_analysis_db(self):
        for path, data in ((self.folder / "absent.db", self.results), (self.article_db, [self.results[0] | {"article_id": "absent"}])):
            with self.subTest(path=path), self.assertRaises((StorageError, AnalysisError)):
                save_analysis(path, self.db, data)
        self.assertFalse(self.db.parent.exists())

    def test_invalid_data_hash_evidence_and_duplicate_create_nothing(self):
        bad_span = copy.deepcopy(self.results[0])
        bad_span["evidence"][0]["quote"] = "없는 근거"
        cases = [[], {}, [self.results[0] | {"category": "unknown"}], [self.results[0] | {"input_hash": "0" * 64}], [bad_span], [self.results[0], self.results[0]]]
        for data in cases:
            with self.subTest(data=type(data).__name__), self.assertRaises((ValidationError, AnalysisError)):
                save_analysis(self.article_db, self.db, data)
        self.assertFalse(self.db.parent.exists())

    def test_alias_paths_and_hardlink_are_rejected(self):
        alias = self.folder / "alias.db"
        os.link(self.article_db, alias)
        for path in (self.article_db, self.folder / "." / "articles.db", alias):
            with self.subTest(path=path), self.assertRaisesRegex(StorageError, "서로 다른"):
                save_analysis(self.article_db, path, self.results)
        self.assertEqual(self.article_db.read_bytes(), self.article_before)

    def test_injected_id_collision_rolls_back_prior_insert(self):
        save_analysis(self.article_db, self.db, self.results)
        before = self.db.read_bytes()
        first = self.results[0] | {"reason": "새 결과"}
        conflict = self.results[1] | {"reason": "충돌 시험"}
        original_hash = json_hash(self.results[1])
        def forced_hash(value):
            return original_hash if value.get("reason") == "충돌 시험" else json_hash(value)
        with patch("saba.analysis_storage.json_hash", side_effect=forced_hash):
            with self.assertRaisesRegex(StorageError, "충돌"):
                save_analysis(self.article_db, self.db, [first, conflict])
        self.assertEqual(self.db.read_bytes(), before)
        self.assertEqual(self.article_db.read_bytes(), self.article_before)

    def test_mid_insert_failure_rolls_back(self):
        save_analysis(self.article_db, self.db, self.results)
        before = self.db.read_bytes()
        real_connect = sqlite3.connect
        inserts = []
        class FailingConnection(sqlite3.Connection):
            def execute(self, sql, parameters=()):
                if sql.startswith("INSERT"):
                    inserts.append(parameters[0])
                    if len(inserts) == 2:
                        raise sqlite3.OperationalError("injected failure")
                return super().execute(sql, parameters)
        def connect(path, *args, **kwargs):
            if path == self.db:
                kwargs["factory"] = FailingConnection
            return real_connect(path, *args, **kwargs)
        changed = [r | {"reason": "새 합성 결과"} for r in self.results]
        with patch("saba.analysis_storage.sqlite3.connect", side_effect=connect), self.assertRaises(sqlite3.OperationalError):
            save_analysis(self.article_db, self.db, changed)
        self.assertEqual(len(inserts), 2)
        self.assertEqual(self.db.read_bytes(), before)

    def test_absent_query_missing_id_and_valid_empty_db(self):
        for query in (lambda: list_analyses(self.db), lambda: get_analysis(self.db, "missing")):
            with self.assertRaises(StorageError):
                query()
        self.assertFalse(self.db.parent.exists())
        self.db.parent.mkdir()
        with closing(sqlite3.connect(self.db)) as connection:
            connection.execute(CREATE_TABLE)
        self.assertEqual(list_analyses(self.db), [])
        empty = self.cli("--list-analyses", "--analysis-db", self.db)
        self.assertEqual(empty.returncode, 0)
        self.assertIn("과거 분석 결과 0건", empty.stdout)
        self.assertEqual(self.cli("--show-analysis", "missing", "--analysis-db", self.db).returncode, 1)
        with self.assertRaises(StorageError):
            get_analysis(self.db, "missing")

    def test_query_is_readonly_and_works_without_article_db(self):
        save_analysis(self.article_db, self.db, self.results)
        before = self.db.read_bytes()
        self.article_db.unlink()  # 임시 시험 DB만 제거하여 과거 조회를 확인한다.
        real_connect = sqlite3.connect
        calls = []
        def connect(*args, **kwargs):
            calls.append((args, kwargs))
            return real_connect(*args, **kwargs)
        with patch("saba.storage.sqlite3.connect", side_effect=connect):
            list_analyses(self.db)
            get_analysis(self.db, json_hash(self.results[0]))
        self.assertTrue(all("mode=ro" in args[0] and kwargs["uri"] for args, kwargs in calls))
        self.assertEqual(self.db.read_bytes(), before)

    def test_unexpected_structure_is_preserved(self):
        self.db.parent.mkdir()
        with closing(sqlite3.connect(self.db)) as connection:
            connection.execute(CREATE_TABLE.replace("status TEXT NOT NULL", "status TEXT NOT NULL UNIQUE"))
        before = self.db.read_bytes()
        for query in (lambda: list_analyses(self.db), lambda: save_analysis(self.article_db, self.db, self.results)):
            with self.assertRaisesRegex(StorageError, "구조"):
                query()
        self.assertEqual(self.db.read_bytes(), before)

    def test_record_column_json_snapshot_and_time_corruption(self):
        save_analysis(self.article_db, self.db, self.results)
        analysis_id = json_hash(self.results[0])
        with closing(sqlite3.connect(self.db)) as connection:
            original = connection.execute("SELECT * FROM analyses WHERE analysis_id = ?", (analysis_id,)).fetchone()
            changed_snapshot = input_payload(self.articles[0])
            changed_snapshot["texts"]["original_title"] = "변조된 합성 제목"
            cases = [("status", "wrong"), ("article_id", "wrong"), ("input_hash", "0" * 64), ("rules_version", "v2"), ("result_json", "DO_NOT_LOG_RAW_BODY"), ("result_json", json.dumps(self.results[0] | {"reason": "변조된 결과"})), ("input_json", "{}"), ("input_json", json.dumps(changed_snapshot)), ("stored_at", "2026-10-06T00:00:00+09:00")]
            for column, value in cases:
                with self.subTest(column=column):
                    with connection:
                        connection.execute(f"UPDATE analyses SET {column} = ? WHERE analysis_id = ?", (value, analysis_id))
                    with self.assertRaises(StorageError) as error:
                        get_analysis(self.db, analysis_id)
                    self.assertNotIn("DO_NOT_LOG_RAW_BODY", str(error.exception))
                    with connection:
                        connection.execute("DELETE FROM analyses WHERE analysis_id = ?", (analysis_id,))
                        connection.execute("INSERT INTO analyses VALUES (?, ?, ?, ?, ?, ?, ?, ?)", original)

    def test_snapshot_field_type_normalization_and_extra_fields(self):
        snapshot = input_payload(self.articles[0])
        for update in ({"schema_version": True}, {"schema_version": 2}, {"url": "ftp://example.com"}, {"published_at": "2026-10-06"}, {"provider": "invented"}, {"rules_version": "v2"}, {"input_kind": "title_only"}, {"texts": {"original_title": " title "}}):
            with self.subTest(update=update), self.assertRaises(ValidationError):
                InputSnapshot.model_validate(snapshot | update)

    def test_sql_input_is_data(self):
        data = copy.deepcopy(ARTICLE_DATA[1])
        data["article_id"] = "test'); DROP TABLE analyses; --"
        article = validate_articles([data])[0]
        save_articles(self.article_db, [article])
        result = self.results[1] | {"article_id": article.article_id, "input_hash": json_hash(input_payload(article))}
        save_analysis(self.article_db, self.db, [result])
        self.assertEqual(get_analysis(self.db, json_hash(result))["result"]["article_id"], article.article_id)
        with self.assertRaises(StorageError):
            get_analysis(self.db, "' OR 1=1 --")

    def test_cli_first_repeat_history_and_separate_queries(self):
        first = self.import_cli()
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertIn("신규 3건", first.stderr)
        repeat = self.import_cli()
        self.assertEqual(repeat.returncode, 0)
        self.assertIn("신규 0건 · 동일 결과 3건 생략", repeat.stderr)
        changed = self.folder / "different.json"
        changed.write_text(json.dumps([self.results[0] | {"reason": "다른 합성 결과"}]), encoding="utf-8")
        self.assertEqual(self.import_cli(changed).returncode, 0)
        listing = self.cli("--list-analyses", "--analysis-db", self.db)
        self.assertEqual(listing.returncode, 0)
        self.assertIn("과거 분석 결과 4건", listing.stdout)
        self.assertNotIn(self.results[0]["summary"], listing.stdout + listing.stderr)
        show = self.cli("--show-analysis", json_hash(self.results[0]), "--analysis-db", self.db)
        self.assertEqual(show.returncode, 0)
        self.assertEqual(json.loads(show.stdout)["result"], self.results[0])
        self.assertNotIn(self.results[0]["summary"], show.stderr)
        self.assertEqual(self.article_db.read_bytes(), self.article_before)

    def test_cli_read_and_validation_failures_no_db(self):
        for payload in ("[", json.dumps([self.results[0] | {"summary": " "}]), json.dumps([self.results[0] | {"input_hash": "0" * 64, "reason": "DO_NOT_LOG_RAW_BODY"}])):
            path = self.folder / "invalid.json"
            path.write_text(payload, encoding="utf-8")
            result = self.import_cli(path)
            self.assertEqual(result.returncode, 1)
            self.assertNotIn("DO_NOT_LOG_RAW_BODY", result.stdout + result.stderr)
        self.assertFalse(self.db.parent.exists())

    def test_cli_query_errors_options_and_no_creation(self):
        for args in (("--list-analyses",), ("--show-analysis", "missing")):
            self.assertEqual(self.cli(*args, "--analysis-db", self.db).returncode, 1)
        invalid = [("--analysis-db", self.db), ("--list-analyses", "--db", self.article_db), ("--import-analysis", RESULTS, "--articles", ARTICLES), ("--list-analyses", "--show-analysis", "id"), ("--show-analysis", " "), ("--validate-analysis", RESULTS, "--articles", ARTICLES, "--analysis-db", self.db)]
        for args in invalid:
            self.assertEqual(self.cli(*args).returncode, 2)
        self.assertFalse(self.db.parent.exists())

    def test_default_paths_and_existing_commands_do_not_create_db(self):
        self.assertEqual(DEFAULT_ANALYSIS_DB, ROOT / "data/analysis.db")
        for args in ((), ("--validate-json", ARTICLES), ("--validate-analysis", RESULTS, "--articles", ARTICLES)):
            self.assertEqual(self.cli(*args).returncode, 0)
        self.assertFalse(self.db.parent.exists())
        result = self.cli("--help")
        self.assertIn("--import-analysis", result.stdout)
        result = subprocess.run([sys.executable, "-X", "utf8", "-c", "from saba.analysis_storage import DEFAULT_ANALYSIS_DB; print(DEFAULT_ANALYSIS_DB)"], cwd=self.folder, capture_output=True, encoding="utf-8")
        self.assertEqual(Path(result.stdout.strip()), DEFAULT_ANALYSIS_DB)

    def test_locked_and_corrupt_database_safe_errors(self):
        save_analysis(self.article_db, self.db, self.results)
        with closing(sqlite3.connect(self.db)) as connection:
            connection.execute("BEGIN EXCLUSIVE")
            result = self.import_cli()
            connection.rollback()
        self.assertEqual(result.returncode, 1)
        self.assertIn("SQLITE_BUSY", result.stderr)
        corrupt = self.folder / "corrupt.db"
        corrupt.write_bytes(b"DO_NOT_LOG_RAW_BODY invalid sqlite")
        result = self.cli("--list-analyses", "--analysis-db", corrupt)
        self.assertEqual(result.returncode, 1)
        self.assertIn("SQLITE_NOTADB", result.stderr)
        self.assertNotIn("DO_NOT_LOG_RAW_BODY", result.stderr)

    def test_permission_error_safe_and_no_network(self):
        from saba.__main__ import main
        real_connect = sqlite3.connect
        def connect(path, *args, **kwargs):
            if path == self.db:
                raise PermissionError(13, "DO_NOT_LOG_RAW_BODY")
            return real_connect(path, *args, **kwargs)
        with patch.object(sys, "argv", ["saba", "--import-analysis", str(RESULTS), "--db", str(self.article_db), "--analysis-db", str(self.db)]), patch("saba.analysis_storage.sqlite3.connect", side_effect=connect), patch("socket.create_connection", side_effect=AssertionError("network")), self.assertLogs(level="ERROR") as logs:
            self.assertEqual(main(), 1)
        self.assertNotIn("DO_NOT_LOG_RAW_BODY", "\n".join(logs.output))
        self.assertEqual(self.article_db.read_bytes(), self.article_before)

    def test_successful_import_never_requests_network(self):
        from saba.__main__ import main
        with patch.object(sys, "argv", ["saba", "--import-analysis", str(RESULTS), "--db", str(self.article_db), "--analysis-db", str(self.db)]), patch("socket.create_connection", side_effect=AssertionError("network")), patch("saba.__main__.fetch_feed", side_effect=AssertionError("feed")):
            self.assertEqual(main(), 0)
        self.assertEqual(len(list_analyses(self.db)), 3)


if __name__ == "__main__":
    unittest.main()
