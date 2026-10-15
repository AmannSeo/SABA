from datetime import datetime
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
import zipfile

from saba.daily import DailyConfig, register_command
from saba.deploy import DeployError, backup, restore

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "saba.ps1"
CONFIG = DailyConfig(time="08:00", random_delay_minutes=5, weekdays=("MON", "TUE", "WED", "THU", "FRI"),
                     max_analysis_calls=20, max_insight_calls=20, send=True)
NOW = datetime(2026, 10, 12, 11, 0, 0)


class BackupRestoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "data" / "sub").mkdir(parents=True)
        (self.root / "config").mkdir()
        (self.root / "data" / "saba.db").write_bytes(b"db")
        (self.root / "data" / "sub" / "cache.json").write_text("{}", encoding="utf-8")
        (self.root / "data" / "admin.pid").write_text("123", encoding="utf-8")
        (self.root / "config" / "daily.json").write_text("{}", encoding="utf-8")
        (self.root / "src").mkdir()
        (self.root / "src" / "code.py").write_text("x", encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def test_backup_contains_data_and_config_only(self):
        path = backup(self.root, NOW)
        self.assertEqual(path.name, "saba_backup_20261012_1100.zip")
        names = set(zipfile.ZipFile(path).namelist())
        self.assertEqual(names, {"data/saba.db", "data/sub/cache.json", "config/daily.json"})

    def test_restore_keeps_previous_folders(self):
        path = backup(self.root, NOW)
        (self.root / "data" / "saba.db").write_bytes(b"newer")
        kept = restore(path, self.root, NOW)
        self.assertEqual(kept, ["data_before_restore_20261012_110000", "config_before_restore_20261012_110000"])
        self.assertEqual((self.root / "data" / "saba.db").read_bytes(), b"db")
        self.assertEqual((self.root / "data_before_restore_20261012_110000" / "saba.db").read_bytes(), b"newer")

    def test_restore_rejects_paths_outside_data_and_config(self):
        for bad in ("../evil.txt", "src/code.py", "data/../../evil.txt", "C:/evil.txt"):
            path = self.root / "bad.zip"
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("data/ok.txt", "ok")
                archive.writestr(bad, "x")
            with self.assertRaises(DeployError, msg=bad):
                restore(path, self.root, NOW)
            self.assertTrue((self.root / "data" / "saba.db").exists())  # 거부 시 아무것도 바꾸지 않음
            self.assertFalse((self.root / "data" / "ok.txt").exists())


class RegisterTests(unittest.TestCase):
    def test_default_registration_unchanged(self):
        command = register_command(CONFIG)
        self.assertNotIn("StartWhenAvailable", command)  # 꺼져 있던 날은 건너뜀 (D-080)
        self.assertNotIn("-Password", command)
        self.assertIn("New-ScheduledTaskSettingsSet -WakeToRun -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries", command)  # D-081
        self.assertIn("-Settings $s", command)

    def test_unattended_prompts_password_without_storing(self):
        command = register_command(CONFIG, unattended=True)
        self.assertIn("New-ScheduledTaskSettingsSet -StartWhenAvailable", command)
        self.assertIn("Get-Credential", command)
        self.assertIn("-Password $c.GetNetworkCredential().Password", command)  # 입력 창 값만 사용
        self.assertIn("-Settings $s", command)


class EntryTests(unittest.TestCase):
    """SABA.exe 진입점 (D-069): -m 모듈 실행을 python -m 과 같게."""

    def run_entry(self, *args):
        import sys
        return subprocess.run([sys.executable, str(ROOT / "scripts" / "saba_entry.py"), *args],
                              capture_output=True, timeout=60, cwd=ROOT)

    def test_runs_saba_module_with_arguments(self):
        result = self.run_entry("-m", "saba.daily", "--register", "--unattended")
        self.assertEqual(result.returncode, 0)
        self.assertIn(b"StartWhenAvailable", result.stdout)

    def test_rejects_other_modules(self):
        for args in ((), ("-m", "os"), ("--run",)):
            self.assertEqual(self.run_entry(*args).returncode, 2, args)

    def test_frozen_registers_executable_itself(self):
        import importlib
        import sys
        from unittest.mock import patch
        import saba.daily
        with patch.object(sys, "frozen", True, create=True), patch.object(sys, "executable", r"D:\SABA\SABA.exe"):
            module = importlib.reload(saba.daily)
            self.assertIn(r"-Execute 'D:\SABA\SABA.exe'", module.register_command(CONFIG))
        importlib.reload(saba.daily)
        self.assertIn(".venv", str(saba.daily.PYTHON))


@unittest.skipUnless(shutil.which("powershell"), "PowerShell 없음")
class ScriptTests(unittest.TestCase):
    def run_script(self, *args):
        result = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(SCRIPT), *args],
                                capture_output=True, timeout=120)
        return result.returncode, result.stdout.decode("utf-8", errors="replace")

    def test_script_parses_and_has_bom(self):
        self.assertTrue(SCRIPT.read_bytes().startswith(b"\xef\xbb\xbf"))  # Windows PowerShell 5.1 한글
        check = ("$e=$null; [System.Management.Automation.Language.Parser]::ParseFile("
                 f"'{SCRIPT}', [ref]$null, [ref]$e) | Out-Null; $e.Count")
        out = subprocess.run(["powershell", "-NoProfile", "-Command", check], capture_output=True, text=True, timeout=60)
        self.assertEqual(out.stdout.strip(), "0")

    def test_without_apply_only_prints(self):
        code, out = self.run_script("register", "-Unattended")
        self.assertEqual(code, 0)
        self.assertIn("확인만 합니다", out)
        self.assertIn("StartWhenAvailable", out)
        for command in ("unregister", "uninstall"):
            code, out = self.run_script(command)
            self.assertEqual(code, 0)
            self.assertIn("확인만 합니다", out)


if __name__ == "__main__":
    unittest.main()
