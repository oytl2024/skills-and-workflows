"""Non-model Windows sandbox probe using synthetic fixtures, never real credentials."""

import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


PROBE_TIMEOUT_SECONDS = 30
PROBE_LOG_BYTES = 4096


def run_probe_command(argv: list[str], log_root: Path) -> dict:
    """Input: argv list and log directory Path. Output: dict. Bound probe lifetime without descendant-held capture pipes."""
    stdout_path, stderr_path = log_root / "stdout.log", log_root / "stderr.log"
    timed_out, cleanup_required = False, False
    with stdout_path.open("w", encoding="utf-8") as stdout, stderr_path.open("w", encoding="utf-8") as stderr:
        process = subprocess.Popen(argv, stdout=stdout, stderr=stderr, shell=False)
        try:
            returncode = process.wait(timeout=PROBE_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            timed_out, returncode = True, -1
            if process.poll() is None:
                try:
                    stopped = subprocess.run(["C:\\Windows\\System32\\taskkill.exe", "/PID", str(process.pid), "/T", "/F"],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10, check=False, shell=False)
                    cleanup_required = stopped.returncode != 0
                except (OSError, subprocess.TimeoutExpired):
                    cleanup_required = True
                if cleanup_required:
                    try:
                        process.kill()
                    except OSError:
                        cleanup_required = True
            try:
                process.wait(timeout=5)
            except (OSError, subprocess.TimeoutExpired):
                cleanup_required = True
    with stdout_path.open("rb") as stream:
        output = stream.read(PROBE_LOG_BYTES).decode("utf-8", errors="replace")
    with stderr_path.open("rb") as stream:
        error = stream.read(PROBE_LOG_BYTES).decode("utf-8", errors="replace")
    return {"returncode": returncode, "timed_out": timed_out, "cleanup_required": cleanup_required,
            "stdout": output, "stderr": error}


def main() -> int:
    """Input: CLI args. Output: exit int and JSON. Test synthetic outside-root read/write under Codex sandbox."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--child", nargs=2)
    parser.add_argument("--backend", choices=("elevated", "unelevated", "mxc"), default="unelevated")
    parser.add_argument("--explicit-deny", action="store_true")
    args = parser.parse_args()
    if args.child:
        read_path, write_path = map(Path, args.child)
        result = {}
        try:
            read_path.read_bytes()
            result["outside_read_denied"] = False
        except PermissionError:
            result["outside_read_denied"] = True
        try:
            write_path.write_text("synthetic-write-probe", encoding="ascii")
            result["outside_write_denied"] = False
        except PermissionError:
            result["outside_write_denied"] = True
        print(json.dumps(result))
        return 0
    project = Path(__file__).resolve().parents[1]
    output = project / "output" / "maintenance-sandbox-probe"
    output.mkdir(parents=True, exist_ok=True)
    executable = shutil.which("codex")
    if not executable:
        raise RuntimeError("Codex CLI unavailable")
    with tempfile.TemporaryDirectory(dir=output) as directory:
        root = Path(directory)
        workspace = root / "worker"
        workspace.mkdir()
        sentinel = root / "synthetic-secret.txt"
        sentinel.write_text("not-a-real-secret", encoding="ascii")
        filesystem = {":minimal": "read", ":workspace_roots": {".": "write"}}
        if args.explicit_deny:
            filesystem = {":root": "read", ":workspace_roots": {".": "write"}, str(sentinel): "deny"}
        profile = "permissions.maintenance_probe.filesystem={" + ",".join(
            json.dumps(key) + "=" + ('{"."="write"}' if isinstance(value, dict) else json.dumps(value))
            for key, value in filesystem.items()) + "}"
        argv = [executable, "sandbox", "-C", str(workspace), "-P", "maintenance_probe",
                "-c", 'windows.sandbox="' + args.backend + '"',
                "-c", profile,
                "-c", "permissions.maintenance_probe.network.enabled=false", sys.executable,
                str(Path(__file__).resolve()), "--child", str(sentinel), str(root / "write-probe.txt")]
        completed = run_probe_command(argv, output)
        result = {"returncode": completed["returncode"], "model_calls": 0, "platform_calls": 0,
                  "timed_out": completed["timed_out"], "cleanup_required": completed["cleanup_required"],
                  "backend": args.backend, "explicit_deny": args.explicit_deny}
        if completed["returncode"] == 0:
            result.update(json.loads(completed["stdout"]))
        else:
            result["probe_error"] = "probe_timeout" if completed["timed_out"] else completed["stderr"][-1200:]
        result["patch_execution_allowed"] = False
        result["network_and_usage_proven"] = False
        (output / "latest.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
        print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
