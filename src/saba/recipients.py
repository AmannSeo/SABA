"""수신자·그룹·부서·허용 도메인 관리 (D-074, D-075). 저장은 data/recipients.db (Git 제외).

명단 (이름·메일) 은 개인정보다. 로그·변경 기록에는 주소 대신 건수만 남긴다.
이 단계에서는 저장·관리만 하고 실제 발송은 TEST 1명 (send_mail.TEST_ADDRESS) 만 허용한다.
"""

from contextlib import closing
import csv
from dataclasses import dataclass, field
from datetime import datetime, timezone
import io
from pathlib import Path
import re
import sqlite3

DEFAULT_PATH = Path(__file__).resolve().parents[2] / "data" / "recipients.db"
DEFAULT_GROUPS = ("TEST", "파일럿")
DEFAULT_DEPARTMENTS = ("경영전략팀 · 사업지원팀", "기술개발연구소", "보안사업팀", "STE본부")
DEFAULT_DOMAINS = ("tbell.co.kr",)
ALL_GROUP = "전체"  # 사용 중인 전원 (저장하지 않는 자동 그룹)
CSV_HEADER = ("이름", "메일", "부서", "그룹")
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@([A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+)")
NAME_LIMIT = 40
GROUP = re.compile(r"[^\s;,]{1,20}")

SCHEMA = """
CREATE TABLE IF NOT EXISTS recipients (id INTEGER PRIMARY KEY, name TEXT NOT NULL, email TEXT NOT NULL UNIQUE,
  department TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 1, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS groups (name TEXT PRIMARY KEY);
CREATE TABLE IF NOT EXISTS memberships (recipient_id INTEGER NOT NULL REFERENCES recipients(id) ON DELETE CASCADE,
  group_name TEXT NOT NULL REFERENCES groups(name) ON DELETE CASCADE, PRIMARY KEY (recipient_id, group_name));
CREATE TABLE IF NOT EXISTS departments (name TEXT PRIMARY KEY, ordinal INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS domains (domain TEXT PRIMARY KEY);
"""


class RecipientError(ValueError):
    pass


@dataclass
class Recipient:
    id: int
    name: str
    email: str
    department: str
    enabled: bool
    groups: list[str] = field(default_factory=list)


def connect(path: Path = DEFAULT_PATH) -> sqlite3.Connection:
    """처음 열 때 표와 기본값 (그룹 TEST·파일럿, 부서 4개, 회사 도메인) 을 만든다."""
    path.parent.mkdir(parents=True, exist_ok=True)
    new = not path.exists()
    connection = sqlite3.connect(path, timeout=5)
    connection.execute("PRAGMA foreign_keys = ON")
    connection.executescript(SCHEMA)
    if new:
        with connection:
            connection.executemany("INSERT OR IGNORE INTO groups VALUES (?)", [(g,) for g in DEFAULT_GROUPS])
            connection.executemany("INSERT OR IGNORE INTO departments VALUES (?, ?)", [(d, i) for i, d in enumerate(DEFAULT_DEPARTMENTS)])
            connection.executemany("INSERT OR IGNORE INTO domains VALUES (?)", [(d,) for d in DEFAULT_DOMAINS])
    return connection


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---- 조회 ----
def groups(path: Path = DEFAULT_PATH) -> list[tuple[str, int]]:
    """(그룹 이름, 사용 중 인원). 맨 앞은 자동 그룹 '전체'."""
    with closing(connect(path)) as c:
        total = c.execute("SELECT COUNT(*) FROM recipients WHERE enabled = 1").fetchone()[0]
        rows = c.execute("SELECT g.name, COUNT(r.id) FROM groups g LEFT JOIN memberships m ON m.group_name = g.name "
                         "LEFT JOIN recipients r ON r.id = m.recipient_id AND r.enabled = 1 GROUP BY g.name ORDER BY g.name").fetchall()
    order = {name: i for i, name in enumerate(DEFAULT_GROUPS)}
    return [(ALL_GROUP, total)] + sorted(rows, key=lambda row: (order.get(row[0], 99), row[0]))


def departments(path: Path = DEFAULT_PATH) -> list[tuple[str, int]]:
    with closing(connect(path)) as c:
        return c.execute("SELECT d.name, COUNT(r.id) FROM departments d LEFT JOIN recipients r ON r.department = d.name "
                         "GROUP BY d.name ORDER BY d.ordinal, d.name").fetchall()


def domains(path: Path = DEFAULT_PATH) -> list[str]:
    with closing(connect(path)) as c:
        return [row[0] for row in c.execute("SELECT domain FROM domains ORDER BY domain")]


def recipients(path: Path = DEFAULT_PATH, group: str | None = None) -> list[Recipient]:
    with closing(connect(path)) as c:
        rows = c.execute("SELECT id, name, email, department, enabled FROM recipients ORDER BY department, name").fetchall()
        members: dict[int, list[str]] = {}
        for recipient_id, name in c.execute("SELECT recipient_id, group_name FROM memberships ORDER BY group_name"):
            members.setdefault(recipient_id, []).append(name)
    result = [Recipient(r[0], r[1], r[2], r[3], bool(r[4]), members.get(r[0], [])) for r in rows]
    if group == ALL_GROUP:
        return [r for r in result if r.enabled]
    return [r for r in result if group in r.groups] if group else result


def counts(path: Path = DEFAULT_PATH) -> dict[str, int]:
    people = recipients(path)
    return {"total": len(people), "enabled": sum(r.enabled for r in people)}


# ---- 검증 ----
def validate(name: str, email: str, department: str, group_names: list[str], path: Path = DEFAULT_PATH) -> tuple[str, str, str, list[str]]:
    name, email, department = name.strip(), email.strip().lower(), department.strip()
    group_names = sorted({g.strip() for g in group_names if g.strip() and g.strip() != ALL_GROUP})
    if not 1 <= len(name) <= NAME_LIMIT:
        raise RecipientError(f"이름은 1~{NAME_LIMIT}자여야 합니다.")
    match = EMAIL.fullmatch(email)
    if not match:
        raise RecipientError("메일 주소 형식이 아닙니다.")
    if match.group(1) not in domains(path):
        raise RecipientError(f"허용되지 않은 도메인입니다 ({'·'.join(domains(path))} 만 허용).")
    if department not in [d for d, _ in departments(path)]:
        raise RecipientError(f"부서 목록에 없는 부서입니다 ({department[:20] or '빈 값'}).")
    known = {g for g, _ in groups(path)}
    unknown = [g for g in group_names if g not in known]
    if unknown:
        raise RecipientError(f"없는 그룹입니다 ({', '.join(unknown)[:40]}).")
    return name, email, department, group_names


# ---- 변경 ----
def save(name: str, email: str, department: str, group_names: list[str], enabled: bool = True,
         recipient_id: int | None = None, path: Path = DEFAULT_PATH) -> str:
    """추가 (recipient_id 없음) 또는 수정. 같은 메일이 이미 있으면 추가 대신 오류 (수정은 화면에서)."""
    name, email, department, group_names = validate(name, email, department, group_names, path)
    with closing(connect(path)) as c, c:
        existing = c.execute("SELECT id FROM recipients WHERE email = ?", (email,)).fetchone()
        if recipient_id is None:
            if existing:
                raise RecipientError("이미 등록된 메일 주소입니다.")
            recipient_id = c.execute("INSERT INTO recipients (name, email, department, enabled, updated_at) VALUES (?, ?, ?, ?, ?)",
                                     (name, email, department, int(enabled), _now())).lastrowid
            action = "추가"
        else:
            if existing and existing[0] != recipient_id:
                raise RecipientError("다른 수신자가 이미 쓰는 메일 주소입니다.")
            if c.execute("UPDATE recipients SET name = ?, email = ?, department = ?, enabled = ?, updated_at = ? WHERE id = ?",
                         (name, email, department, int(enabled), _now(), recipient_id)).rowcount == 0:
                raise RecipientError("수신자를 찾지 못했습니다.")
            action = "수정"
        c.execute("DELETE FROM memberships WHERE recipient_id = ?", (recipient_id,))
        c.executemany("INSERT INTO memberships VALUES (?, ?)", [(recipient_id, g) for g in group_names])
    return action


def set_enabled(recipient_id: int, enabled: bool, path: Path = DEFAULT_PATH) -> None:
    with closing(connect(path)) as c, c:
        if c.execute("UPDATE recipients SET enabled = ?, updated_at = ? WHERE id = ?", (int(enabled), _now(), recipient_id)).rowcount == 0:
            raise RecipientError("수신자를 찾지 못했습니다.")


def delete(recipient_id: int, path: Path = DEFAULT_PATH) -> None:
    with closing(connect(path)) as c, c:
        if c.execute("DELETE FROM recipients WHERE id = ?", (recipient_id,)).rowcount == 0:
            raise RecipientError("수신자를 찾지 못했습니다.")


def add_group(name: str, path: Path = DEFAULT_PATH) -> None:
    name = name.strip()
    if not GROUP.fullmatch(name) or name == ALL_GROUP:
        raise RecipientError("그룹 이름은 공백·쉼표·세미콜론 없이 1~20자여야 하고 '전체' 는 쓸 수 없습니다.")
    with closing(connect(path)) as c, c:
        if c.execute("INSERT OR IGNORE INTO groups VALUES (?)", (name,)).rowcount == 0:
            raise RecipientError("이미 있는 그룹입니다.")


def delete_group(name: str, path: Path = DEFAULT_PATH) -> None:
    if name in (ALL_GROUP, "TEST"):
        raise RecipientError("'전체'·'TEST' 그룹은 지울 수 없습니다.")
    with closing(connect(path)) as c, c:
        if c.execute("DELETE FROM groups WHERE name = ?", (name,)).rowcount == 0:
            raise RecipientError("그룹을 찾지 못했습니다.")


def add_department(name: str, path: Path = DEFAULT_PATH) -> None:
    name = name.strip()
    if not 1 <= len(name) <= 30 or "," in name:
        raise RecipientError("부서 이름은 쉼표 없이 1~30자여야 합니다.")
    with closing(connect(path)) as c, c:
        ordinal = c.execute("SELECT COALESCE(MAX(ordinal), 0) + 1 FROM departments").fetchone()[0]
        if c.execute("INSERT OR IGNORE INTO departments VALUES (?, ?)", (name, ordinal)).rowcount == 0:
            raise RecipientError("이미 있는 부서입니다.")


def delete_department(name: str, path: Path = DEFAULT_PATH) -> None:
    with closing(connect(path)) as c, c:
        if c.execute("SELECT COUNT(*) FROM recipients WHERE department = ?", (name,)).fetchone()[0]:
            raise RecipientError("이 부서에 수신자가 있어 지울 수 없습니다. 먼저 수신자 부서를 바꾸세요.")
        if c.execute("DELETE FROM departments WHERE name = ?", (name,)).rowcount == 0:
            raise RecipientError("부서를 찾지 못했습니다.")


def add_domain(domain: str, path: Path = DEFAULT_PATH) -> None:
    domain = domain.strip().lower().lstrip("@")
    if not re.fullmatch(r"[a-z0-9-]+(\.[a-z0-9-]+)+", domain):
        raise RecipientError("도메인 형식이 아닙니다 (예: tbell.co.kr).")
    with closing(connect(path)) as c, c:
        if c.execute("INSERT OR IGNORE INTO domains VALUES (?)", (domain,)).rowcount == 0:
            raise RecipientError("이미 있는 도메인입니다.")


def delete_domain(domain: str, path: Path = DEFAULT_PATH) -> None:
    with closing(connect(path)) as c, c:
        if c.execute("SELECT COUNT(*) FROM domains").fetchone()[0] <= 1:
            raise RecipientError("허용 도메인은 하나 이상 있어야 합니다.")
        used = c.execute("SELECT COUNT(*) FROM recipients WHERE email LIKE ?", (f"%@{domain}",)).fetchone()[0]
        if used:
            raise RecipientError("이 도메인을 쓰는 수신자가 있어 지울 수 없습니다.")
        if c.execute("DELETE FROM domains WHERE domain = ?", (domain,)).rowcount == 0:
            raise RecipientError("도메인을 찾지 못했습니다.")


# ---- CSV (D-075: 이름,메일,부서,그룹 / 그룹 여러 개는 ";") ----
def parse_csv(text: str, path: Path = DEFAULT_PATH) -> list[dict]:
    """미리보기 행: line, name, email, department, groups, status (신규·갱신·오류), error. 저장하지 않는다."""
    text = text.lstrip("\ufeff")
    delimiter = "\t" if "\t" in text.split("\n", 1)[0] else ","  # 엑셀에서 복사해 붙여 넣으면 탭
    existing = {r.email for r in recipients(path)}
    seen: set[str] = set()
    rows = []
    for line_no, cells in enumerate(csv.reader(io.StringIO(text), delimiter=delimiter), 1):
        if not any(c.strip() for c in cells):
            continue
        if line_no == 1 and cells and cells[0].strip() in ("이름", "name", "Name"):
            continue  # 제목 줄
        cells = [c.strip() for c in cells] + [""] * 4
        name, email, department, group_text = cells[:4]
        row = {"line": line_no, "name": name, "email": email.lower(), "department": department,
               "groups": [g.strip() for g in re.split(r"[;|]", group_text) if g.strip()], "status": "", "error": ""}
        try:
            row["name"], row["email"], row["department"], row["groups"] = validate(name, email, department, row["groups"], path)
            if row["email"] in seen:
                raise RecipientError("파일 안에 같은 메일이 또 있습니다.")
            seen.add(row["email"])
            row["status"] = "갱신" if row["email"] in existing else "신규"
        except RecipientError as error:
            row["status"], row["error"] = "오류", str(error)
        rows.append(row)
    return rows


def apply_csv(rows: list[dict], path: Path = DEFAULT_PATH) -> tuple[int, int, int]:
    """미리보기 행 중 신규·갱신만 저장한다 (오류 행은 건너뜀). (신규, 갱신, 건너뜀)."""
    by_email = {r.email: r for r in recipients(path)}
    added = updated = skipped = 0
    for row in rows:
        if row["status"] not in ("신규", "갱신"):
            skipped += 1
            continue
        current = by_email.get(row["email"])
        try:
            save(row["name"], row["email"], row["department"], row["groups"],
                 enabled=current.enabled if current else True, recipient_id=current.id if current else None, path=path)
        except RecipientError:
            skipped += 1
            continue
        if current:
            updated += 1
        else:
            added += 1
    return added, updated, skipped


def export_csv(path: Path = DEFAULT_PATH) -> str:
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\r\n")
    writer.writerow(CSV_HEADER + ("상태",))
    for r in recipients(path):
        writer.writerow((r.name, r.email, r.department, ";".join(r.groups), "사용" if r.enabled else "중지"))
    return "\ufeff" + out.getvalue()  # 엑셀에서 한글이 깨지지 않게 BOM


def template_csv() -> str:
    return "\ufeff" + ",".join(CSV_HEADER) + "\r\n홍길동,example.user@tbell.co.kr,보안사업팀,TEST;파일럿\r\n"
