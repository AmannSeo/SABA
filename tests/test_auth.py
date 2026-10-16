"""작업 5: 계정 저장 (해시·규칙·마지막 관리자), 세션 만료, 로그인 실패 제한."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from saba import auth


class UsersTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        patcher = patch.object(auth, "ITERATIONS", 1000)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.users = auth.Users(Path(temp.name) / "users.json")

    def test_password_stored_only_as_salted_hash(self):
        self.users.add("admin1", "admin", "virtual-pass-1")
        self.users.add("admin2", "admin", "virtual-pass-1")
        text = self.users.path.read_text(encoding="utf-8")
        self.assertNotIn("virtual-pass-1", text)
        data = self.users.load()
        self.assertNotEqual(data["admin1"]["hash"], data["admin2"]["hash"])  # 같은 비밀번호도 소금이 달라 해시가 다르다
        self.assertEqual(self.users.verify("admin1", "virtual-pass-1"), "admin")
        self.assertIsNone(self.users.verify("admin1", "wrong-pass-12"))
        self.assertIsNone(self.users.verify("nobody", "virtual-pass-1"))

    def test_rules(self):
        for user, role, password in (("ab", "admin", "virtual-pass-1"), ("Admin", "admin", "virtual-pass-1"),
                                     ("viewer1", "owner", "virtual-pass-1"), ("viewer1", "viewer", "short1!"),
                                     ("viewer1", "viewer", "abcdefghijkl"), ("viewer1", "viewer", "123456789012")):
            with self.subTest(user=user, role=role, password=password), self.assertRaises(auth.AuthError):
                self.users.add(user, role, password)
        self.users.add("viewer1", "viewer", "virtual-pass-1")
        with self.assertRaises(auth.AuthError):
            self.users.add("viewer1", "viewer", "virtual-pass-2")

    def test_last_admin_cannot_be_deleted_and_password_change(self):
        self.users.add("admin1", "admin", "virtual-pass-1")
        self.users.add("viewer1", "viewer", "virtual-pass-1")
        with self.assertRaisesRegex(auth.AuthError, "마지막 관리자"):
            self.users.delete("admin1")
        self.users.delete("viewer1")
        self.users.set_password("admin1", "virtual-pass-2")
        self.assertIsNone(self.users.verify("admin1", "virtual-pass-1"))
        self.assertEqual(self.users.verify("admin1", "virtual-pass-2"), "admin")

    def test_first_admin_is_atomic_under_concurrent_setup(self):
        from concurrent.futures import ThreadPoolExecutor
        def create(uid):
            try:
                self.users.add(uid, 'admin', 'virtual-pass-1', first_admin=True)
                return True
            except auth.AuthError:
                return False
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(create, ('admin1', 'admin2')))
        self.assertEqual(results.count(True), 1)
        self.assertEqual(len(self.users.load()), 1)

    def test_symbols_only_password_and_corrupt_account_json(self):
        with self.assertRaises(auth.AuthError):
            self.users.add('admin1', 'admin', '!' * 12)
        self.users.path.write_text('{broken', encoding='utf-8')
        with self.assertRaises(auth.AuthError) as caught:
            self.users.load()
        self.assertNotIn('{broken', str(caught.exception))


class ResetPasswordTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        patcher = patch.object(auth, "ITERATIONS", 1000)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.root = Path(temp.name)
        self.users = auth.Users(self.root / "data" / "admin_users.json")
        self.users.add("admin1", "admin", "virtual-pass-1")
        self.out = []

    def reset(self, user, *passwords):
        answers = iter(passwords)
        return auth.reset_password(self.users, ask=lambda _: user, secret=lambda _: next(answers), out=self.out.append)

    def test_reset_sets_new_password_and_logs_without_value(self):
        self.assertEqual(self.reset("admin1", "virtual-new-2", "virtual-new-2"), 0)
        self.assertEqual(self.users.verify("admin1", "virtual-new-2"), "admin")
        self.assertIsNone(self.users.verify("admin1", "virtual-pass-1"))
        log = (self.root / "logs" / "settings_changes.log").read_text(encoding="utf-8")
        self.assertIn("비밀번호 초기화", log)
        self.assertNotIn("virtual-new-2", log + "".join(self.out))

    def test_reset_refuses_mismatch_unknown_and_weak(self):
        for args in (("admin1", "virtual-new-2", "virtual-new-3"), ("nobody", "virtual-new-2", "virtual-new-2"),
                     ("admin1", "short", "short")):
            with self.subTest(args=args):
                self.assertEqual(self.reset(*args), 1)
        self.assertEqual(self.users.verify("admin1", "virtual-pass-1"), "admin")  # 바뀐 것 없음

    def test_no_accounts(self):
        empty = auth.Users(self.root / "data" / "none.json")
        self.assertEqual(auth.reset_password(empty, out=self.out.append), 1)
        self.assertIn("첫 관리자", self.out[-1])


class SessionTests(unittest.TestCase):
    def test_exact_idle_limit_expires_session(self):
        now = [0.0]
        sessions = auth.Sessions(clock=lambda: now[0])
        sid = sessions.create('admin1', 'admin')
        now[0] = auth.SESSION_IDLE
        self.assertIsNone(sessions.get(sid))

    def test_idle_expiry_and_drop(self):
        now = [0.0]
        sessions = auth.Sessions(clock=lambda: now[0])
        sid = sessions.create("admin1", "admin")
        now[0] = auth.SESSION_IDLE - 1
        self.assertEqual(sessions.get(sid).user, "admin1")  # 사용하면 다시 30분
        now[0] += auth.SESSION_IDLE - 1
        self.assertIsNotNone(sessions.get(sid))
        now[0] += auth.SESSION_IDLE + 1
        self.assertIsNone(sessions.get(sid))
        other = sessions.create("viewer1", "viewer")
        sessions.drop(user="viewer1")
        self.assertIsNone(sessions.get(other))
        self.assertIsNone(sessions.get(None))

    def test_lock_after_failures_then_release(self):
        now = [0.0]
        sessions = auth.Sessions(clock=lambda: now[0])
        for _ in range(auth.MAX_FAILURES):
            self.assertFalse(sessions.locked("admin1"))
            sessions.failed("admin1")
        self.assertTrue(sessions.locked("admin1"))
        now[0] += auth.LOCK_SECONDS
        self.assertFalse(sessions.locked("admin1"))
        sessions.failed("admin1")
        self.assertFalse(sessions.locked("admin1"))  # 잠금이 풀리면 다시 센다
        sessions.succeeded("admin1")


class SecretValueTests(unittest.TestCase):
    def test_value_rule(self):
        self.assertTrue(auth.SECRET_VALUE.fullmatch("sk-virtual_123"))
        for bad in ("", "has space", "line\nbreak", "x" * 501):
            self.assertIsNone(auth.SECRET_VALUE.fullmatch(bad))


if __name__ == "__main__":
    unittest.main()
