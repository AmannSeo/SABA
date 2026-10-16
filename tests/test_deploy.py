from datetime import datetime
from pathlib import Path
import json
import os
import re
import runpy
import sys
import types
import shutil
import subprocess
import tempfile
import unittest
import zipfile

from saba.daily import DailyConfig, register_command
from saba.deploy import DeployError, backup, restore
from saba.admin import SECRET_NAMES
from unittest.mock import patch, MagicMock

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

    def test_trial_backup_includes_private_settings_but_not_environment(self):
        required = {"config/sources.json": [{"id": "virtual-source"}],
                    "config/admin.json": {"login": True},
                    "config/public_api.json": {"law": ["virtual-keyword"]},
                    "data/admin_users.json": {"virtual-admin": {"hash": "virtual-hash"}}}
        for name, value in required.items():
            (self.root / name).write_text(json.dumps(value), encoding="utf-8")
        values = {name: f"virtual-environment-only-{i}" for i, name in enumerate(SECRET_NAMES)}
        with patch.dict(os.environ, values):
            archive_path = backup(self.root, NOW)
        with zipfile.ZipFile(archive_path) as archive:
            self.assertTrue(required.keys() <= set(archive.namelist()))
            contents = b"".join(archive.read(name) for name in archive.namelist())
            for value in values.values():
                self.assertNotIn(value.encode(), contents)
        restore(archive_path, self.root, NOW)
        for name, value in required.items():
            self.assertEqual(json.loads((self.root / name).read_text(encoding="utf-8")), value)

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

    def test_encoding_with_error_handler_does_not_crash(self):
        import os
        import sys
        for value in ("utf-8:surrogateescape", "utf-8"):  # Python 형식 "인코딩:오류처리" (2026-10-16 실행 파일 시작 실패)
            result = subprocess.run([sys.executable, str(ROOT / "scripts" / "saba_entry.py"), "-m", "saba.daily", "--register"],
                                    capture_output=True, timeout=60, cwd=ROOT, env={**os.environ, "PYTHONIOENCODING": value})
            self.assertEqual(result.returncode, 0, (value, result.stderr[-300:]))

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

    def test_frozen_layout_roots_and_subprocesses_use_bundle_directory(self):
        with tempfile.TemporaryDirectory() as temp:
            bundle = Path(temp) / 'SABA'
            executable = bundle / 'SABA.exe'
            for name in ('daily', 'deploy', 'admin'):
                module = types.ModuleType('virtual_frozen_' + name)
                module.__file__ = str(bundle / '_internal' / 'saba' / (name + '.py'))
                source = (ROOT / 'src' / 'saba' / (name + '.py')).read_text(encoding='utf-8')
                with patch.object(sys, 'frozen', True, create=True), patch.object(sys, 'executable', str(executable)), \
                        patch.dict(sys.modules, {module.__name__: module}):
                    exec(compile(source, module.__file__, 'exec'), module.__dict__)
                    self.assertEqual(module.ROOT, bundle)
                    if name == 'daily':
                        self.assertEqual(module.PYTHON, executable)
                        command = module.register_command(CONFIG, unattended=True)
                        for text in (str(executable), str(bundle), 'Get-Credential', 'StartWhenAvailable', 'WakeToRun'):
                            self.assertIn(text, command)
                    if name == 'admin':
                        app = module.AdminApp(launch=lambda args: None)
                        self.assertEqual(app.root, bundle)

    def fake_registry(self):
        fake = types.SimpleNamespace(HKEY_CURRENT_USER=object(), OpenKey=MagicMock(), QueryValueEx=MagicMock())
        fake.OpenKey.return_value.__enter__.return_value = object()
        def query(key, name):
            if name == 'SABA_LAW_OC':
                raise FileNotFoundError
            return ('virtual-new-' + name, 1)
        fake.QueryValueEx.side_effect = query
        return fake

    def test_entry_refreshes_six_user_values_without_exposing_them(self):
        namespace = runpy.run_path(str(ROOT / 'scripts' / 'saba_entry.py'))
        self.assertEqual(namespace['SECRET_NAMES'], SECRET_NAMES)
        fake = self.fake_registry()
        with patch.dict(sys.modules, {'winreg': fake}), patch.dict(os.environ, {'OPENAI_API_KEY': 'virtual-old'}, clear=True):
            self.assertIsNone(namespace['refresh_user_environment']())
            self.assertEqual(os.environ['OPENAI_API_KEY'], 'virtual-new-OPENAI_API_KEY')
            self.assertNotIn('SABA_LAW_OC', os.environ)
            self.assertEqual([call.args[1] for call in fake.QueryValueEx.call_args_list], list(SECRET_NAMES))
        fake.OpenKey.assert_called_once_with(fake.HKEY_CURRENT_USER, 'Environment')

    def test_frozen_entry_refreshes_only_operational_commands(self):
        entry = str(ROOT / 'scripts' / 'saba_entry.py')
        cases = [(('saba.daily', '--register'), False), (('saba.deploy', '--backup'), False),
                 (('saba.admin', '--help'), False), (('saba.admin', '--stop'), False),
                 (('saba.admin', '--no-browser'), True), (('saba.daily', '--run'), True)]
        for (name, flag), reads in cases:
            fake = self.fake_registry()
            with patch.object(sys, 'frozen', True, create=True), patch.object(sys, 'argv', [entry, '-m', name, flag]), \
                    patch.dict(sys.modules, {'winreg': fake}), patch.dict(os.environ, {}, clear=True), \
                    patch.object(runpy, 'run_module') as run:
                runpy.run_path(entry, run_name='__main__')
                run.assert_called_once_with(name, run_name='__main__', alter_sys=True)
                self.assertEqual(fake.OpenKey.called, reads)


@unittest.skipUnless(shutil.which("powershell"), "PowerShell 없음")
class ScriptTests(unittest.TestCase):
    def test_packaged_install_uses_no_python_registry_or_scheduler(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'SABA.exe').write_bytes(b'virtual-executable')
            check = root / 'check.ps1'
            source = r"""
$ErrorActionPreference = 'Stop'
$trialRoot = '__ROOT__'
$source = Get-Content -Raw -Encoding UTF8 '__SCRIPT__'
$source = $source.Replace('$Root = Split-Path -Parent $PSScriptRoot', ('$Root = ''' + $trialRoot.Replace("'", "''") + ''''))
$source = $source.Replace('[Environment]::GetEnvironmentVariable($name, "User")', '$null')
$source = $source.Replace('[Environment]::GetEnvironmentVariable($name, "Process")', '$null')
$global:linksSaved = 0
function Register-ScheduledTask { throw 'scheduler access prohibited' }
function New-Object {
    param([string]$ComObject)
    if ($ComObject -ne 'WScript.Shell') { throw 'unexpected COM object' }
    $shell = [pscustomobject]@{}
    $shell | Add-Member ScriptMethod CreateShortcut {
        param($path)
        $link = [pscustomobject]@{TargetPath=''; Arguments=''; WorkingDirectory=''}
        $link | Add-Member ScriptMethod Save { $global:linksSaved += 1 }
        return $link
    }
    return $shell
}
& ([scriptblock]::Create($source)) install
if ($global:linksSaved -ne 2) { throw 'expected two shortcut saves' }
Write-Output 'MOCK_INSTALL_OK'
""".replace('__ROOT__', str(root).replace("'", "''")).replace('__SCRIPT__', str(SCRIPT).replace("'", "''"))
            check.write_text(source, encoding='utf-8-sig')
            result = subprocess.run(['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(check)],
                                    capture_output=True, timeout=60)
            self.assertEqual(result.returncode, 0, result.stderr.decode('utf-8', errors='replace'))
            self.assertIn(b'MOCK_INSTALL_OK', result.stdout)
            self.assertFalse((root / '.venv').exists())
            for folder in ('data', 'logs', 'output', 'backups'):
                self.assertTrue((root / folder).is_dir())

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


class BomConfigTests(unittest.TestCase):
    def test_user_edited_config_with_bom_is_read(self):
        """PowerShell 5 의 Set-Content -Encoding utf8 은 BOM 을 붙인다. 새 PC 에서 직접 고친 설정도 읽혀야 한다."""
        from saba import admin, daily
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "admin.json"
            path.write_bytes(b"\xef\xbb\xbf" + b'{"host":"127.0.0.1","port":8799,"login":true}')
            self.assertEqual(admin.load_admin_config(path), ("127.0.0.1", 8799))
            self.assertTrue(admin.login_enabled(path))
            config = ROOT / "config" / "daily.json"
            bom = Path(directory) / "daily.json"
            bom.write_bytes(b"\xef\xbb\xbf" + config.read_bytes())
            self.assertEqual(daily.load_config(bom).time, daily.load_config(config).time)


class TrialScriptTests(unittest.TestCase):
    def test_build_is_offline_and_pins_frozen_layout(self):
        build = (ROOT / 'scripts' / 'build_exe.ps1').read_text(encoding='utf-8-sig')
        self.assertNotIn('pip install', build)
        self.assertIn('import PyInstaller', build)
        self.assertIn('--contents-directory _internal', build)
        self.assertIn('기존 묶음에 운영 폴더', build)
        self.assertIn('"admin.json", "daily.json", "departments.json", "public_api.json", "sources.json"', build)
        self.assertIn('foreach ($folder in "templates", "sign")', build)

    def test_secret_names_and_presence_only_guidance(self):
        script = SCRIPT.read_text(encoding="utf-8-sig")
        names = re.search(r'^\$SecretNames = (.*)$', script, re.M).group(1)
        self.assertEqual(tuple(re.findall(r'"([A-Z_]+)"', names)), SECRET_NAMES)
        function = script.split("function Show-Secrets {", 1)[1].split("function Find-Python", 1)[0]
        self.assertIn('if ($value) { "있음" } else { "없음" }', function)
        self.assertIn('Write-Output "  $name : $state"', function)
        self.assertNotIn('Write-Output "$value', function)
        self.assertIn("설정 화면에서 Secret 6개", function)
        self.assertNotIn("직접 입력 필요", script)


if __name__ == "__main__":
    unittest.main()
