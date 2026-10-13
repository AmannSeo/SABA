"""발송 이력 (D-076, D-077). data/send_history.db (Git 제외).

회차를 먼저 만들고 수신자마다 결과를 바로 저장한다. 결과 구분 (D-077):
- 성공: 서버가 받았다고 답함
- 실패: 서버가 거부했다고 답함 (받지 않은 것이 확실)
- 미시도: 보내지 않음 (로그인 실패·중단 등)
- 불명확: 보내는 도중·이후 연결이 끊김, 또는 "전송 중" 인 채로 끝남 (받았을 수도 있음, 자동·실패 재발송에서 제외)
SMTP 만으로 정확히 한 번 배달을 보장할 수는 없다. 주소는 관리 화면에서만 보여 주고 로그에는 건수만 쓴다.
"""

from contextlib import closing
from dataclasses import dataclass
from datetime import datetime
import hashlib
from pathlib import Path
import sqlite3

DEFAULT_PATH = Path(__file__).resolve().parents[2] / "data" / "send_history.db"
OK, FAILED, NOT_TRIED, UNCLEAR, SENDING = "성공", "실패", "미시도", "불명확", "전송 중"
RESENDABLE = (FAILED, NOT_TRIED)  # 받지 않은 것이 확실한 결과만 다시 보낼 수 있다 (D-077)
SCHEMA = """
CREATE TABLE IF NOT EXISTS sends (id INTEGER PRIMARY KEY, at TEXT NOT NULL, origin TEXT NOT NULL, target TEXT NOT NULL,
  mail_file TEXT NOT NULL DEFAULT '', mail_sha256 TEXT NOT NULL DEFAULT '', parent_id INTEGER REFERENCES sends(id),
  finished INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS results (send_id INTEGER NOT NULL REFERENCES sends(id) ON DELETE CASCADE,
  email TEXT NOT NULL, status TEXT NOT NULL, detail TEXT NOT NULL DEFAULT '', PRIMARY KEY (send_id, email));
"""


class SendLogError(RuntimeError):
    pass


@dataclass
class Result:
    email: str
    status: str
    detail: str = ""

    @property
    def ok(self) -> bool:
        return self.status == OK


@dataclass
class Send:
    id: int
    at: str
    origin: str
    target: str
    mail_file: str
    mail_sha256: str
    parent_id: int | None
    finished: bool
    counts: dict

    @property
    def total(self) -> int:
        return sum(self.counts.values())

    @property
    def ok(self) -> int:
        return self.counts.get(OK, 0)

    @property
    def failed(self) -> int:
        """성공이 아닌 사람 수 (실패·미시도·불명확)."""
        return self.total - self.ok


def _connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=5)
    connection.execute("PRAGMA foreign_keys = ON")
    columns = {row[1] for row in connection.execute("PRAGMA table_info(results)")}
    if columns and "status" not in columns:  # 예전 구조: 표 추가도 하지 않는다. 마이그레이션은 별도 승인 (D-077)
        connection.close()
        raise SendLogError("발송 이력 DB 구조가 예전 형식입니다. 마이그레이션은 별도 승인이 필요합니다.")
    connection.executescript(SCHEMA)
    return connection


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def start(origin: str, target: str, emails: list[str], *, mail_file: str = "", mail_sha256: str = "",
          parent_id: int | None = None, path: Path = DEFAULT_PATH, at: datetime | None = None) -> int:
    """회차와 수신자 행 (미시도) 을 먼저 만든다. 실패하면 SendLogError (호출자는 보내지 않는다)."""
    try:
        with closing(_connect(path)) as c, c:
            send_id = c.execute("INSERT INTO sends (at, origin, target, mail_file, mail_sha256, parent_id) VALUES (?, ?, ?, ?, ?, ?)",
                                ((at or datetime.now()).strftime("%Y-%m-%d %H:%M:%S"), origin, target, mail_file,
                                 mail_sha256, parent_id)).lastrowid
            c.executemany("INSERT INTO results VALUES (?, ?, ?, '')", [(send_id, e, NOT_TRIED) for e in dict.fromkeys(emails)])
        return send_id
    except sqlite3.Error as error:
        raise SendLogError(f"발송 이력 저장 실패: {type(error).__name__}") from None


def mark(send_id: int, email: str, status: str, detail: str = "", path: Path = DEFAULT_PATH) -> None:
    try:
        with closing(_connect(path)) as c, c:
            if c.execute("UPDATE results SET status = ?, detail = ? WHERE send_id = ? AND email = ?",
                         (status, detail[:200], send_id, email)).rowcount != 1:
                raise SendLogError("발송 이력에 없는 수신자입니다.")
    except sqlite3.Error as error:
        raise SendLogError(f"발송 이력 저장 실패: {type(error).__name__}") from None


def finish(send_id: int, path: Path = DEFAULT_PATH) -> None:
    """회차를 마친다. "전송 중" 으로 남은 사람은 불명확으로 바꾼다."""
    try:
        with closing(_connect(path)) as c, c:
            c.execute("UPDATE results SET status = ?, detail = '전송 결과를 받지 못함' WHERE send_id = ? AND status = ?",
                      (UNCLEAR, send_id, SENDING))
            c.execute("UPDATE sends SET finished = 1 WHERE id = ?", (send_id,))
    except sqlite3.Error as error:
        raise SendLogError(f"발송 이력 저장 실패: {type(error).__name__}") from None


def record(origin: str, target: str, results: list[Result], mail_file: str = "", path: Path = DEFAULT_PATH,
           at: datetime | None = None) -> int:
    """한 번에 기록 (TEST 주소 1명 발송처럼 결과가 이미 정해진 경우)."""
    send_id = start(origin, target, [r.email for r in results], mail_file=mail_file, path=path, at=at)
    for result in results:
        mark(send_id, result.email, result.status, result.detail, path)
    finish(send_id, path)
    return send_id


def _status(raw: str) -> str:
    return UNCLEAR if raw == SENDING else raw  # 전송 중인 채로 남았으면 (중단) 받았는지 알 수 없다


def sends(path: Path = DEFAULT_PATH, limit: int = 200) -> list[Send]:
    if not path.exists():
        return []
    with closing(_connect(path)) as c:
        rows = c.execute("SELECT id, at, origin, target, mail_file, mail_sha256, parent_id, finished FROM sends "
                         "ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        result = []
        for row in rows:
            counts: dict[str, int] = {}
            for status, n in c.execute("SELECT status, COUNT(*) FROM results WHERE send_id = ? GROUP BY status", (row[0],)):
                key = _status(status)
                counts[key] = counts.get(key, 0) + n
            result.append(Send(*row[:7], bool(row[7]), counts))
    return result


def results(send_id: int, path: Path = DEFAULT_PATH) -> list[Result]:
    if not path.exists():
        return []
    with closing(_connect(path)) as c:
        return [Result(email, _status(status), detail) for email, status, detail in
                c.execute("SELECT email, status, detail FROM results WHERE send_id = ? ORDER BY status, email", (send_id,))]


def resend_targets(send_id: int, path: Path = DEFAULT_PATH) -> list[str]:
    """원회차에서 받지 않은 것이 확실한 사람 (실패·미시도) 중 이후 모든 재발송 (재발송의 재발송 포함) 에서
    성공·불명확·전송 중이 아닌 사람 (D-077)."""
    if not path.exists():
        return []
    with closing(_connect(path)) as c:
        base = [e for e, s in c.execute("SELECT email, status FROM results WHERE send_id = ?", (send_id,)) if s in RESENDABLE]
        later = {e for (e,) in c.execute(
            "WITH RECURSIVE tree(id) AS (SELECT id FROM sends WHERE parent_id = ? "
            "UNION SELECT s.id FROM sends s JOIN tree t ON s.parent_id = t.id) "
            "SELECT r.email FROM results r JOIN tree t ON t.id = r.send_id WHERE r.status NOT IN (?, ?)",
            (send_id, FAILED, NOT_TRIED))}
    return [e for e in base if e not in later]
