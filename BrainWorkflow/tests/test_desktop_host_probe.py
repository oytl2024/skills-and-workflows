"""Offline host inventory and packaging-contract fixtures; no real backend."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from unittest.mock import Mock
from types import SimpleNamespace


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "probe_desktop_host.py"


class DesktopHostProbeTests(unittest.TestCase):
    def load_probe(self):
        """Input: self. Output: module. Load the standalone script without product startup."""
        self.assertTrue(SCRIPT.is_file(), "Task1 host probe is not implemented")
        spec = importlib.util.spec_from_file_location("desktop_host_probe", SCRIPT)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_absent_dependencies_do_not_claim_exe_feasibility(self):
        """Input: absent inventory fixture. Output: None. Catch false packaged acceptance."""
        probe = self.load_probe()
        result = probe.assess_host({"system": "Windows", "packages": {}, "webview2": []})
        self.assertEqual(result["candidate"], "pywebview + PyInstaller + system WebView2")
        self.assertFalse(result["dependencies_present"])
        self.assertFalse(result["packaged_exe_verified"])
        self.assertEqual(set(result["missing"]), {"pywebview", "pythonnet", "pyinstaller", "WebView2", ".NET Framework"})

    def test_present_metadata_is_not_runtime_or_build_proof(self):
        """Input: installed-version fixture. Output: None. Catch metadata promoted to working EXE."""
        probe = self.load_probe()
        inventory = {"system": "Windows", "packages": {
            "pywebview": "6.0", "pythonnet": "3.0.5", "pyinstaller": "6.16"},
            "webview2": [{"scope": "user", "version": "140.0.1.2"}],
            "dotnet": {"status": "registered", "release": 533509}}
        result = probe.assess_host(inventory)
        self.assertTrue(result["dependencies_present"])
        self.assertFalse(result["packaged_exe_verified"])
        self.assertFalse(result["runtime_load_verified"])
        inventory["system"] = "Linux"
        self.assertFalse(probe.assess_host(inventory)["dependencies_present"])

    def test_malformed_runtime_evidence_and_missing_clr_fail_closed(self):
        """Input: invalid runtime/CLR fixtures. Output: None. Catch registered-but-unusable assumptions."""
        probe = self.load_probe()
        inventory = {"system": "Windows", "packages": {
            "pywebview": "6.0", "pythonnet": "3.0.5", "pyinstaller": "6.16"},
            "webview2": [{"scope": "machine", "version": "0.0.0.0"}],
            "dotnet": {"status": "unavailable"}}
        result = probe.assess_host(inventory)
        self.assertFalse(result["dependencies_present"])
        self.assertIn("WebView2", result["missing"])
        self.assertIn(".NET Framework", result["missing"])
        for value in (None, 123, "", "0.0.0.0", "private text", "1." + "1" * 5000, "\u00b2.\u00b2"):
            self.assertFalse(probe.valid_version(value))

    def test_registry_probe_is_bounded_and_filters_browser_and_zero_versions(self):
        """Input: fake registry API. Output: None. Catch Edge mistaken for WebView or unbounded enumeration."""
        probe = self.load_probe()
        rows = [("Microsoft Edge", "140.0.0.1"), ("Microsoft Edge WebView2 Runtime", "0.0.0.0"),
                ("Microsoft Edge WebView2 Runtime", "155.0.4283.62")]
        key = Mock()
        key.__enter__ = Mock(return_value=key)
        key.__exit__ = Mock(return_value=False)
        current = [0]
        visits = []

        def enum_key(parent, index):
            """Input: fake key, int index. Output: str. Record bounded reads of synthetic clients."""
            visits.append(index)
            current[0] = index
            return str(index)

        def query_value(client, name):
            """Input: fake key, value name str. Output: tuple. Return synthetic product/version only."""
            row = rows[min(current[0], 2)]
            return (row[0] if name == "name" else row[1], 1)

        registry = SimpleNamespace(HKEY_CURRENT_USER=1, HKEY_LOCAL_MACHINE=2,
            KEY_WOW64_32KEY=4, KEY_WOW64_64KEY=8, KEY_READ=16,
            OpenKey=Mock(return_value=key), QueryInfoKey=lambda client: (10000, 0, 0),
            EnumKey=enum_key, QueryValueEx=query_value)
        with patch.dict(sys.modules, {"winreg": registry}), patch.object(probe.os, "name", "nt"):
            found = probe.webview2_inventory()
        self.assertEqual(found, [{"scope": "user", "version": "155.0.4283.62"},
                                 {"scope": "machine", "version": "155.0.4283.62"}])
        self.assertEqual(max(visits), 63)
        self.assertEqual(len(visits), 256)

    def test_inventory_handles_missing_broken_metadata_without_importing_hosts(self):
        """Input: failing metadata provider. Output: None. Catch unsafe host imports/error leakage."""
        probe = self.load_probe()
        with patch.object(probe.metadata, "version", side_effect=RuntimeError("private detail")), \
                patch.object(probe, "webview2_inventory", return_value=[]), \
                patch.object(subprocess, "Popen", side_effect=AssertionError("no processes")):
            result = probe.probe_host()
        encoded = json.dumps(result)
        self.assertNotIn("private detail", encoded)
        self.assertFalse(result["assessment"]["packaged_exe_verified"])
        self.assertTrue(all(item["status"] == "unavailable" for item in result["packages"].values()))

    def test_assets_and_health_are_application_relative_not_cwd(self):
        """Input: Unicode/space fixture roots. Output: None. Catch cwd and foreign-health acceptance."""
        probe = self.load_probe()
        with tempfile.TemporaryDirectory(prefix="desktop fixture ") as temporary:
            root = Path(temporary) / "app \u6d4b\u8bd5"
            assets = root / "frontend" / "dist"
            assets.mkdir(parents=True)
            (assets / "index.html").write_text("<html>offline</html>", encoding="utf-8")
            expected = {"app": "BrainWorkflow", "workflow_root": str(root),
                        "knowledge_root": str(root / "knowledge"), "runs_root": str(root / "runs"),
                        "code_revision": "fixture-revision"}
            health = dict(expected, server_revision="fixture-instance")
            command = [str(root / "python.exe"), "-m", "wqb.cli", "launch-console"]
            good = probe.validate_launch(root, "frontend/dist/index.html", command,
                                         frozen=False, expected=expected, health=health)
            self.assertTrue(good["assets_valid"])
            self.assertTrue(good["health_owned"])
            self.assertTrue(good["entry_valid"])
            for field in expected:
                with self.subTest(field=field):
                    wrong = dict(health, **{field: "foreign"})
                    self.assertFalse(probe.validate_launch(root, "frontend/dist/index.html", command,
                        frozen=False, expected=expected, health=wrong)["health_owned"])
            for relative in ("../outside.html", "https://example.invalid", "missing.html"):
                self.assertFalse(probe.validate_launch(root, relative, command, frozen=False,
                    expected=expected, health=health)["assets_valid"])
            self.assertFalse(probe.validate_launch(root, "frontend/dist/index.html", command,
                frozen=False, expected=expected, health=dict(health, server_revision=""))["health_owned"])

    def test_frozen_entry_rejects_recursive_python_module_dispatch(self):
        """Input: frozen child argv fixtures. Output: None. Catch reusing development Python entry."""
        probe = self.load_probe()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for command, valid in ((["BrainWorkflow.exe", "-m", "wqb.cli"], False),
                                   (["BrainWorkflow.exe", "--backend"], True),
                                   (["python.exe", "--backend"], False),
                                   (["BrainWorkflow.exe"], False)):
                result = probe.validate_launch(root, "index.html", command, frozen=True,
                                               expected={}, health={})
                self.assertEqual(result["entry_valid"], valid)
                self.assertFalse(result["packaged_exe_verified"])

    def test_source_command_runs_only_fixture_module(self):
        """Input: fake CLI in temporary cwd. Output: None. Verify source argv without product launch."""
        self.load_probe()
        from wqb.desktop import DesktopConfig, backend_command, child_environment
        with tempfile.TemporaryDirectory(prefix="desktop source ") as temporary:
            root = Path(temporary)
            module = root / "wqb"
            module.mkdir()
            (module / "__init__.py").write_text("", encoding="utf-8")
            (module / "cli.py").write_text("import json, sys\nprint(json.dumps(sys.argv[1:]))\n", encoding="utf-8")
            command = backend_command(DesktopConfig(root, root / "knowledge", root / "runs"),
                                      18765, Path(sys.executable))
            env = child_environment({"SystemRoot": "C:/Windows", "windir": "C:/Windows", "PYTHONUTF8": "1"})
            result = subprocess.run([command[0], "-B", *command[1:]], cwd=root, env=env,
                                    capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout), ["launch-console", "--console-host", "127.0.0.1",
                "--console-port", "18765", "--no-open-browser", "--knowledge-root", str(root / "knowledge"),
                "--run-dir", str(root / "runs")])


if __name__ == "__main__":
    unittest.main()
