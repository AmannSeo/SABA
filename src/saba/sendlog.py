"""발송 이력 (D-076). data/send_history.db (Git 제외).

회차마다 대상·인원·성공·실패, 수신자마다 결과를 남긴다. 주소는 관리 화면에서만 보여 주고 로그에는 건수만 쓴다.
"""

from contextlib import closing
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import sqlite3

DEFAULT_PATH = Path(__file__).resolve().parents[2] / "data" / "send_history.db"
SCHEMA = """
CREATE TABLE IF NOT EXISTS sends (id INTEGER PRIMARY KEY, at TEXT NOT NULL, origin TEXT NOT NULL, target TEXT NOT NULL,
  total INTEGER NOT NULL, ok INTEGER NOT NULL, failed INTEGER NOT NULL, mail_file TEXT NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS results (send_id INTEGER NOT NULL REFERENCES sends(id) ON DELETE CASCADE,
  email TEXT NOT NULL, ok INTEGER NOT NULL, detail TEXT NOT NULL DEFAULT '');
"""


@dataclass
class Send:
    id: int
    at: str
    origin: str
    target: str
    total: int
    ok: int
    failed: int
    mail_file: str


@dataclass
class Result:
    email: str
    ok: bool
    detail: str


def _connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=5)
    connection.execute("PRAGMA foreign_keys = ON")
    connection.executescript(SCHEMA)
    return connection


def record(origin: str, target: str, results: list[Result], mail_file: str = "", path: Path = DEFAULT_PATH,
           at: datetime | None = None) -> int:
    ok = sum(r.ok for r in results)
    with closing(_connect(path)) as c, c:
        send_id = c.execute("INSERT INTO sends (at, origin, target, total, ok, failed, mail_file) VALUES (?, ?, ?, ?, ?, ?, ?)",
                            ((at or datetime.now()).strftime("%Y-%m-%d %H:%M:%S"), origin, target, len(results), ok,
                             len(results) - ok, mail_file)).lastrowid
        c.executemany("INSERT INTO results VALUES (?, ?, ?, ?)", [(send_id, r.email, int(r.ok), r.detail) for r in results])
    return send_id


def sends(path: Path = DEFAULT_PATH, limit: int = 200) -> list[Send]:
    if not path.exists():
        return []
    with closing(_connect(path)) as c:
        return [Send(*row) for row in c.execute(
            "SELECT id, at, origin, target, total, ok, failed, mail_file FROM sends ORDER BY id DESC LIMIT ?", (limit,))]


def results(send_id: int, path: Path = DEFAULT_PATH) -> list[Result]:
    if not path.exists():
        return []
    with closing(_connect(path)) as c:
        return [Result(email, bool(ok), detail) for email, ok, detail in
                c.execute("SELECT email, ok, detail FROM results WHERE send_id = ? ORDER BY ok, email", (send_id,))]
