"""관리 페이지 계정·로그인 세션·Secret 저장 (작업 5, 2026-10-14 사용자 결정). 표준 라이브러리만 쓴다.

- 계정: data/admin_users.json (Git 제외). 비밀번호는 소금 포함 PBKDF2-HMAC-SHA256 해시만 저장한다.
- 역할: admin (모든 변경), viewer (조회만, 수신자 메일 가림).
- 세션: 서버 메모리, 30분 동안 요청이 없으면 만료. 관리 페이지를 다시 켜면 다시 로그인한다.
- 로그인 5회 연속 실패하면 그 아이디는 60초 동안 막는다.
- Secret: Windows 사용자 환경 변수 (HKCU\\Environment) 에 저장한다. 값은 화면·로그·변경 이력에 남기지 않는다.
"""

from dataclasses import dataclass, field
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import threading
import time

ROLES = {"admin": "관리자", "viewer": "조회자"}
USERS_PATH = Path(__file__).resolve().parents[2] / "data" / "admin_users.json"
ITERATIONS = 310_000  # 테스트는 줄여서 쓴다
SESSION_IDLE = 30 * 60
MAX_FAILURES, LOCK_SECONDS = 5, 60
USER_ID = re.compile(r"[a-z0-9][a-z0-9._-]{2,29}")
MIN_PASSWORD = 10


class AuthError(ValueError):
    """화면에 그대로 보여도 되는 안내 문구만 담는다 (비밀번호·값 없음)."""


def _hash(password: str, salt: bytes, iterations: int) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations).hex()


def check_password_rule(password: str) -> None:
    if len(password) < MIN_PASSWORD or len(password) > 128:
        raise AuthError(f"비밀번호는 {MIN_PASSWORD}~128자여야 합니다.")
    if not any(c.isalpha() for c in password) or not any(not c.isalpha() for c in password):
        raise AuthError("비밀번호는 글자와 숫자·기호를 섞어야 합니다.")


class Users:
    def __init__(self, path: Path = USERS_PATH):
        self.path = path
        self._lock = threading.Lock()

    def load(self) -> dict:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}
        except json.JSONDecodeError:
            raise AuthError("계정 파일이 JSON 형식이 아닙니다. data/admin_users.json 을 확인하세요.") from None
        if not isinstance(data, dict) or not isinstance(data.get("users"), dict):
            raise AuthError("계정 파일 형식이 올바르지 않습니다. data/admin_users.json 을 확인하세요.")
        return data["users"]

    def _save(self, users: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix(".tmp")
        temp.write_text(json.dumps({"users": users}, ensure_ascii=False, indent=1), encoding="utf-8")
        temp.replace(self.path)

    def any(self) -> bool:
        return bool(self.load())

    def list(self) -> list[tuple[str, str]]:
        return sorted((uid, u["role"]) for uid, u in self.load().items())

    def add(self, user_id: str, role: str, password: str, *, first_admin: bool = False) -> None:
        if not USER_ID.fullmatch(user_id):
            raise AuthError("아이디는 영문 소문자·숫자로 시작하는 3~30자 (소문자·숫자·.-_) 여야 합니다.")
        if role not in ROLES:
            raise AuthError("역할은 관리자 또는 조회자여야 합니다.")
        check_password_rule(password)
        with self._lock:
            users = self.load()
            if first_admin and (users or role != "admin"):
                raise AuthError("첫 관리자 계정 설정이 이미 끝났거나 역할이 올바르지 않습니다.")
            if user_id in users:
                raise AuthError("이미 있는 아이디입니다.")
            salt = secrets.token_bytes(16)
            users[user_id] = {"role": role, "salt": salt.hex(), "iterations": ITERATIONS,
                              "hash": _hash(password, salt, ITERATIONS)}
            self._save(users)

    def set_password(self, user_id: str, password: str) -> None:
        check_password_rule(password)
        with self._lock:
            users = self.load()
            if user_id not in users:
                raise AuthError("계정을 찾지 못했습니다.")
            salt = secrets.token_bytes(16)
            users[user_id].update(salt=salt.hex(), iterations=ITERATIONS, hash=_hash(password, salt, ITERATIONS))
            self._save(users)

    def delete(self, user_id: str) -> None:
        with self._lock:
            users = self.load()
            if user_id not in users:
                raise AuthError("계정을 찾지 못했습니다.")
            if users[user_id]["role"] == "admin" and sum(u["role"] == "admin" for u in users.values()) == 1:
                raise AuthError("마지막 관리자 계정은 지울 수 없습니다.")
            del users[user_id]
            self._save(users)

    def verify(self, user_id: str, password: str) -> str | None:
        """맞으면 역할, 틀리면 None. 없는 아이디도 같은 시간이 걸리게 해시를 한 번 계산한다."""
        user = self.load().get(user_id)
        if user is None:
            _hash(password, b"0" * 16, ITERATIONS)
            return None
        actual = _hash(password, bytes.fromhex(user["salt"]), int(user["iterations"]))
        return user["role"] if secrets.compare_digest(actual, user["hash"]) else None


@dataclass
class Session:
    user: str
    role: str
    last_seen: float


@dataclass
class Sessions:
    """메모리 세션과 로그인 실패 제한. clock 은 테스트에서 바꾼다."""
    clock: object = time.monotonic
    _sessions: dict = field(default_factory=dict)
    _failures: dict = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def create(self, user: str, role: str) -> str:
        sid = secrets.token_urlsafe(32)
        with self._lock:
            self._sessions[sid] = Session(user, role, self.clock())
        return sid

    def get(self, sid: str | None) -> Session | None:
        if not sid:
            return None
        with self._lock:
            session = self._sessions.get(sid)
            if session is None:
                return None
            if self.clock() - session.last_seen >= SESSION_IDLE:
                del self._sessions[sid]
                return None
            session.last_seen = self.clock()
            return session

    def drop(self, sid: str | None = None, *, user: str | None = None) -> None:
        with self._lock:
            for key in [k for k, s in self._sessions.items() if k == sid or (user and s.user == user)]:
                del self._sessions[key]

    def locked(self, user_id: str) -> bool:
        count, since = self._failures.get(user_id, (0, 0.0))
        return count >= MAX_FAILURES and self.clock() - since < LOCK_SECONDS

    def failed(self, user_id: str) -> None:
        count, since = self._failures.get(user_id, (0, 0.0))
        if count >= MAX_FAILURES and self.clock() - since >= LOCK_SECONDS:
            count = 0  # 잠금이 풀린 뒤 다시 센다
        self._failures[user_id] = (count + 1, self.clock())

    def succeeded(self, user_id: str) -> None:
        self._failures.pop(user_id, None)


SECRET_VALUE = re.compile(r"[\x21-\x7e]{1,500}")  # 공백·줄바꿈·제어 문자 없는 1~500자


def set_user_env(name: str, value: str) -> None:
    """Windows 사용자 환경 변수에 저장하고 이 프로세스에도 바로 반영한다. 다른 열린 프로그램은 다시 시작해야 읽는다."""
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment", 0, winreg.KEY_SET_VALUE) as key:
        winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)
    os.environ[name] = value
    try:  # 새로 여는 프로그램이 바뀐 값을 읽도록 알린다 (실패해도 저장은 끝났다)
        import ctypes
        ctypes.windll.user32.SendMessageTimeoutW(0xFFFF, 0x001A, 0, "Environment", 0x0002, 2000, None)
    except (AttributeError, OSError):
        pass


def reset_password(users: Users, *, ask=input, secret=None, log_path: Path | None = None, out=print) -> int:
    """이 PC 에서 계정 비밀번호를 다시 정한다 (2026-10-16 사용자 결정: 잊었을 때 PC 에서 초기화).

    관리 페이지가 127.0.0.1 전용이라 이 PC 의 Windows 로그인을 본인 확인으로 본다. 비밀번호는 화면에 보이지 않게 받고
    어디에도 기록하지 않는다. 변경 사실만 설정 변경 이력에 남긴다.
    """
    import getpass
    from saba.history import append_change
    secret = secret or getpass.getpass
    accounts = users.list()
    if not accounts:
        out("계정이 없습니다. 관리 페이지를 열면 첫 관리자 계정 만들기 화면이 나옵니다.")
        return 1
    for user_id, role in accounts:
        out(f"  {user_id} ({ROLES[role]})")
    user_id = ask("비밀번호를 다시 정할 아이디: ").strip()
    if user_id not in dict(accounts):
        out("없는 아이디입니다. 바뀐 것은 없습니다.")
        return 1
    password = secret(f"새 비밀번호 ({MIN_PASSWORD}자 이상, 글자와 숫자·기호 함께, 화면에 보이지 않음): ")
    if password != secret("한 번 더 입력: "):
        out("두 비밀번호가 다릅니다. 바뀐 것은 없습니다.")
        return 1
    try:
        users.set_password(user_id, password)
    except AuthError as error:
        out(f"바뀐 것은 없습니다: {error}")
        return 1
    append_change(log_path or users.path.parents[1] / "logs" / "settings_changes.log",
                  {f"계정 {user_id}": ("", "비밀번호 초기화 (이 PC 명령)")}, False)
    out(f"완료: {user_id} 의 비밀번호를 바꿨습니다. 관리 페이지가 켜져 있으면 다시 시작한 뒤 새 비밀번호로 로그인하세요.")
    return 0


if __name__ == "__main__":
    import sys
    if sys.argv[1:] != ["--reset-password"]:
        print("사용법: python -m saba.auth --reset-password  (이 PC 에서 계정 비밀번호 초기화)")
        raise SystemExit(2)
    raise SystemExit(reset_password(Users()))
