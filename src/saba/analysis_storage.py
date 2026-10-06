"""기사 DB는 읽기만 하고, 분석 결과와 입력 스냅샷을 별도 DB에 보관한다."""

from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
import sqlite3

from pydantic import ValidationError

from saba.analysis import (
    AnalysisResult, InputSnapshot, canonical_json, input_payload, json_hash,
    validate_analysis, validate_snapshot_result,
)
from saba.schema import utc_datetime
from saba.storage import StorageError, list_articles, read_connection

DEFAULT_ANALYSIS_DB = Path(__file__).resolve().parents[2] / "data" / "analysis.db"
CREATE_TABLE = """
CREATE TABLE analyses (
    analysis_id TEXT PRIMARY KEY NOT NULL,
    article_id TEXT NOT NULL,
    input_hash TEXT NOT NULL,
    rules_version TEXT NOT NULL,
    status TEXT NOT NULL,
    result_json TEXT NOT NULL,
    input_json TEXT NOT NULL,
    stored_at TEXT NOT NULL
)
"""


def check_structure(connection: sqlite3.Connection) -> None:
    objects = connection.execute(
        "SELECT type, name, sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY name"
    ).fetchall()
    if (len(objects) != 1 or objects[0][:2] != ("table", "analyses")
            or "".join(objects[0][2].split()).casefold() != "".join(CREATE_TABLE.split()).casefold()):
        raise StorageError("분석 DB 구조가 예상과 다릅니다. 자동 변경하지 않았습니다.")


def restore_record(row: tuple) -> dict:
    try:
        result = AnalysisResult.model_validate_json(row[5])
        snapshot = InputSnapshot.model_validate_json(row[6])
        validate_snapshot_result(result, snapshot)
        expected = (json_hash(result.model_dump(mode="json")), result.article_id,
                    result.input_hash, result.rules_version, result.status)
        if row[:5] != expected or not isinstance(row[7], str):
            raise ValueError
        if utc_datetime(row[7]).isoformat() != row[7]:
            raise ValueError
    except (ValidationError, ValueError, TypeError, OverflowError):
        raise StorageError("분석 DB의 결과·스냅샷·ID·주요 컬럼이 일치하지 않습니다.") from None
    return {"analysis_id": row[0], "stored_at": row[7],
            "result": result.model_dump(mode="json"), "input": snapshot.model_dump()}


def save_analysis(article_path: Path, analysis_path: Path, value: object) -> tuple[int, int]:
    if (article_path.resolve() == analysis_path.resolve()
            or (article_path.exists() and analysis_path.exists() and article_path.samefile(analysis_path))):
        raise StorageError("기사 DB와 분석 DB는 서로 다른 파일이어야 합니다.")
    articles = list_articles(article_path)
    results = validate_analysis(value, articles)
    by_id = {article.article_id: article for article in articles}
    prepared = []
    for result in results:
        snapshot = InputSnapshot.model_validate(input_payload(by_id[result.article_id]))
        validate_snapshot_result(result, snapshot)
        data = result.model_dump(mode="json")
        prepared.append((json_hash(data), result.article_id, result.input_hash, result.rules_version,
                         result.status, canonical_json(data), canonical_json(snapshot.model_dump())))
    existed = analysis_path.exists()
    analysis_path.parent.mkdir(parents=True, exist_ok=True)
    inserted = skipped = 0
    stored_at = datetime.now(timezone.utc).isoformat()
    with closing(sqlite3.connect(analysis_path, timeout=5)) as connection:
        with connection:
            connection.execute("BEGIN IMMEDIATE")
            if not existed:
                connection.execute(CREATE_TABLE)
            check_structure(connection)
            for values in prepared:
                row = connection.execute("SELECT * FROM analyses WHERE analysis_id = ?", (values[0],)).fetchone()
                if row is not None:
                    record = restore_record(row)
                    if (canonical_json(record["result"]) != values[5]
                            or canonical_json(record["input"]) != values[6]):
                        raise StorageError("분석 ID 충돌 1건: 신규 저장 0건. 입력 전체를 Rollback합니다.")
                    skipped += 1
                    continue
                connection.execute("INSERT INTO analyses VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (*values, stored_at))
                inserted += 1
    return inserted, skipped


def list_analyses(path: Path) -> list[dict]:
    with closing(read_connection(path)) as connection:
        check_structure(connection)
        rows = connection.execute("SELECT * FROM analyses ORDER BY stored_at, analysis_id").fetchall()
        return [restore_record(row) for row in rows]


def get_analysis(path: Path, analysis_id: str) -> dict:
    with closing(read_connection(path)) as connection:
        check_structure(connection)
        row = connection.execute("SELECT * FROM analyses WHERE analysis_id = ?", (analysis_id,)).fetchone()
        if row is None:
            raise StorageError("analysis_id: 해당 결과가 분석 DB에 없습니다.")
        return restore_record(row)
