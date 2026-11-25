"""Local cleaner allowlist tests; only isolated fake workspace files are disposable."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/clean_temp.ps1'
POWERSHELL = shutil.which('pwsh') or 'C:/Program Files/PowerShell/7/pwsh.exe'


@unittest.skipUnless(os.name == 'nt', 'Windows cleanup entry')
class SafeTempCleanupTests(unittest.TestCase):
    def setUp(self):
        """Input: TestCase. Output: isolated minimal product/vault; never target actual runs or knowledge."""
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.product = self.root / 'skills-and-workflows/BrainWorkflow'
        for name in ('wqb', 'tests', 'scripts', 'output/desktop-application/installed/BrainWorkflow'):
            (self.product / name).mkdir(parents=True)
        (self.root / 'AGENTS.md').write_text('offline test', encoding='utf-8')
        base = self.product / 'output/desktop-application/installed'
        (base / 'BrainWorkflow/BrainWorkflow.exe').write_bytes(b'fixture')
        (base / 'installation.json').write_text(json.dumps(dict(code_revision='r',
            exe_sha256=hashlib.sha256(b'fixture').hexdigest())), encoding='utf-8')
        (base / 'acceptance.json').write_text(json.dumps(dict(passed=True, source_revision='r')), encoding='utf-8')

    def run_cleaner(self, apply=False):
        """Input: apply bool. Output: JSON plan/result from PowerShell functions in this fake workspace only."""
        quote = lambda value: "'" + str(value).replace("'", "''") + "'"
        command = '. ' + quote(SCRIPT) + ' -FunctionsOnly; $p=Get-TempCleanupPlan -WorkspaceRoot ' + quote(self.root)
        if apply:
            command += '; Invoke-TempCleanupPlan -WorkspaceRoot ' + quote(self.root) + ' -Plan $p | ConvertTo-Json -Depth 5'
        else:
            command += '; $p | ConvertTo-Json -Depth 5'
        process = subprocess.run([POWERSHELL, '-NoProfile', '-Command', command], capture_output=True,
            text=True, encoding='utf-8', timeout=30, env={**os.environ, 'SystemRoot': 'C:/Windows'})
        self.assertEqual(process.returncode, 0, process.stderr)
        return json.loads(process.stdout)

    def test_preview_then_delete_cache_preserves_real_data(self):
        cache = self.product / 'wqb/__pycache__'
        cache.mkdir()
        (cache / 'sample.cpython-312.pyc').write_bytes(b'bytecode')
        keep = [self.root / 'knowledge/raw/source.md', self.root / 'runs/research/run_state.json',
            self.root / 'runs/daily_simulation_budget/today.json', self.product / '.git/config']
        for path in keep:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('keep', encoding='utf-8')
        plan = self.run_cleaner()
        self.assertEqual(len(plan['Candidates']), 1)
        self.assertTrue(cache.exists())
        result = self.run_cleaner(apply=True)
        self.assertEqual(result['DeletedCount'], 1)
        self.assertFalse(cache.exists())
        self.assertTrue(all(path.read_text() == 'keep' for path in keep))

    def test_policy_blocked_build_and_unknown_cache_contents_are_skipped(self):
        cache = self.product / 'wqb/__pycache__'
        cache.mkdir()
        (cache / 'credentials.json').write_text('do not read', encoding='utf-8')
        blocked = self.product / 'output/desktop-application/20261125-094407-1915'
        blocked.mkdir()
        (blocked / 'input-manifest.json').write_text('[]')
        self.assertEqual(self.run_cleaner()['Candidates'], [])
        self.assertTrue(cache.exists())
        self.assertTrue(blocked.exists())

    def test_old_build_requires_valid_current_installation(self):
        build = self.product / 'output/desktop-application/20000101-000000-0001'
        (build / 'source/wqb').mkdir(parents=True)
        (build / 'input-manifest.json').write_text('[]')
        os.utime(build, (946684800, 946684800))
        self.assertEqual(len(self.run_cleaner()['Candidates']), 1)
        receipt = self.product / 'output/desktop-application/installed/installation.json'
        receipt.write_text('{}')
        self.assertEqual(self.run_cleaner()['Candidates'], [])

    def test_locked_cache_is_skipped(self):
        cache = self.product / 'wqb/__pycache__'
        cache.mkdir()
        item = cache / 'busy.pyc'
        item.write_bytes(b'cache')
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
            wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
        kernel.CreateFileW.restype = wintypes.HANDLE
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel.CreateFileW(str(item), 0x80000000, 0, None, 3, 0, None)
        self.assertNotEqual(handle, ctypes.c_void_p(-1).value)
        try:
            self.assertEqual(self.run_cleaner(apply=True)['DeletedCount'], 0)
            self.assertTrue(item.exists())
        finally:
            kernel.CloseHandle(handle)

    def test_recent_build_and_browser_profile_are_never_candidates(self):
        for name in ('20000101-000000-0001', '20990101-000000-0002'):
            build = self.product / 'output/desktop-application' / name
            build.mkdir()
            (build / 'input-manifest.json').write_text('[]')
            (build / 'source/wqb').mkdir(parents=True)
        old = self.product / 'output/desktop-application/20000101-000000-0001'
        (old / 'browser').mkdir()
        os.utime(old, (946684800, 946684800))
        self.assertEqual(self.run_cleaner()['Candidates'], [])

    def test_changed_plan_cannot_delete_new_contents(self):
        cache = self.product / 'wqb/__pycache__'
        cache.mkdir()
        (cache / 'sample.pyc').write_bytes(b'cache')
        quoted = lambda p: "'" + str(p).replace("'", "''") + "'"
        command = '. '+quoted(SCRIPT)+' -FunctionsOnly; $p=Get-TempCleanupPlan '+quoted(self.root)
        command += '; New-Item -ItemType File -Path '+quoted(cache / 'new.pyc')+' | Out-Null'
        command += '; Invoke-TempCleanupPlan '+quoted(self.root)+' $p | ConvertTo-Json -Depth 4'
        process = subprocess.run([POWERSHELL, '-NoProfile', '-Command', command], capture_output=True,
            text=True, encoding='utf-8', timeout=30, env={**os.environ, 'SystemRoot': 'C:/Windows'})
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertEqual(json.loads(process.stdout)['DeletedCount'], 0)
        self.assertTrue(cache.exists())
