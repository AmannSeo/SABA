"""검증된 기사 저장과 읽기 전용 조회. 연결은 각 작업 후 닫는다."""

from contextlib import closing
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3

from pydantic import ValidationError

from saba.schema import Article, validate_articles


DEFAULT_DB = Path(__file__).resolve().parents[2] / "data" / "saba.db"

CREATE_TABLE = """
CREATE TABLE articles (
    article_id TEXT PRIMARY KEY NOT NULL,
    schema_version INTEGER NOT NULL,
    source_id TEXT NOT NULL,
    url TEXT NOT NULL,
    published_at TEXT,
    collected_at TEXT NOT NULL,
    article_json TEXT NOT NULL,
    stored_at TEXT NOT NULL
)
"""

class StorageError(ValueError):
    """기사 내용 없이 보고할 수 있는 저장·조회 오류."""


def check_structure(connection: sqlite3.Connection) -> None:
    objects = connection.execute(
        "SELECT type, name, sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY name"
    ).fetchall()
    # 이 단계에서 생성한 단일 테이블 정의만 허용한다. 별도 제약·트리거도 임의 수용하지 않는다.
    if (
        len(objects) != 1
        or objects[0][:2] != ("table", "articles")
        or "".join(objects[0][2].split()).casefold() != "".join(CREATE_TABLE.split()).casefold()
    ):
        raise StorageError("DB 구조가 예상과 다릅니다. 자동 변경하지 않았습니다.")


def normalized_json(article: Article) -> str:
    return json.dumps(
        article.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def restore_article(row: tuple[str, str]) -> Article:
    try:
        article = Article.model_validate_json(row[1])
    except (ValidationError, TypeError):
        raise StorageError("DB의 article_json이 기사 Schema와 일치하지 않습니다.") from None
    if article.article_id != row[0]:
        raise StorageError("DB의 article_id와 article_json 식별자가 일치하지 않습니다.")
    return article


def save_articles(path: Path, articles: list[Article]) -> tuple[int, int]:
    # 수정된 모델을 전달하더라도 전체 재검증을 DB 생성보다 먼저 수행한다.
    articles = validate_articles([article.model_dump(mode="json") for article in articles])
    existed = path.exists()
    path.parent.mkdir(parents=True, exist_ok=True)
    inserted = skipped = 0
    stored_at = datetime.now(timezone.utc).isoformat()
    with closing(sqlite3.connect(path, timeout=5)) as connection:
        with connection:
            connection.execute("BEGIN IMMEDIATE")
            if not existed:
                connection.execute(CREATE_TABLE)
            check_structure(connection)
            for index, article in enumerate(articles):
                payload = normalized_json(article)
                row = connection.execute(
                    "SELECT article_id, article_json FROM articles WHERE article_id = ?",
                    (article.article_id,),
                ).fetchone()
                if row is not None:
                    if normalized_json(restore_article(row)) != payload:
                        raise StorageError(
                            f"$[{index}].article_id: 기존 기사와 데이터가 달라 충돌했습니다. 입력 전체를 Rollback합니다."
                        )
                    skipped += 1
                    continue
                connection.execute(
                    """INSERT INTO articles
                    (article_id, schema_version, source_id, url, published_at,
                     collected_at, article_json, stored_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        article.article_id,
                        article.schema_version,
                        article.source_id,
                        str(article.url),
                        article.published_at.isoformat() if article.published_at else None,
                        article.collected_at.isoformat(),
                        payload,
                        stored_at,
                    ),
                )
                inserted += 1
    return inserted, skipped


def read_connection(path: Path) -> sqlite3.Connection:
    if not path.exists():
        raise StorageError("DB 파일이 없습니다. 저장 명령으로 DB를 먼저 생성하세요.")
    return sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=5)


def list_articles(path: Path) -> list[Article]:
    with closing(read_connection(path)) as connection:
        check_structure(connection)
        rows = connection.execute(
            "SELECT article_id, article_json FROM articles ORDER BY article_id"
        ).fetchall()
        return [restore_article(row) for row in rows]


def get_article(path: Path, article_id: str) -> Article:
    with closing(read_connection(path)) as connection:
        check_structure(connection)
        row = connection.execute(
            "SELECT article_id, article_json FROM articles WHERE article_id = ?", (article_id,)
        ).fetchone()
        if row is None:
            raise StorageError("article_id: 해당 기사가 DB에 없습니다.")
        return restore_article(row)
