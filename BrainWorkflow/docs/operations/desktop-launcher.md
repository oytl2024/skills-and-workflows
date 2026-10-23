# Desktop Launcher

## Entry Points And Backend Compatibility

Double-click workspace `BrainWorkflow.vbs` or package `launch-desktop.vbs`.
The matching `.cmd` files are terminal-friendly diagnostic entries. These open
an installed Edge/Chrome app-mode window, not a rewritten native UI. Launching
the app does not start a workflow. Closing its window leaves the backend alive;
launching again reuses the matching backend and focuses or reopens the window.

Reuse now requires the loaded source fingerprint (`code_revision`) to match the
launcher, including uncommitted Python edits. The fingerprint is captured once
when each process starts. A same-workspace older backend is refused with its
port and an explicit restart diagnostic; the launcher does not silently reuse
old code or start a competing worker. After maintenance, restart the verified
Console backend before handing it to operations. Closing the app window alone
does not stop that backend or apply code updates.

Python selection: `BRAINWORKFLOW_PYTHON` (full executable path), then package or
workspace `.venv`, then PATH Python/py. Install the project dependencies in that
interpreter. `BRAINWORKFLOW_BROWSER` can select an installed Edge/Chrome executable
when the normal ProgramFiles/LOCALAPPDATA environment is unavailable.

Defaults are workspace `knowledge` and `runs`. Optional arguments are
`--knowledge-root`, `--runs-root`, and `--port`. Quote paths with spaces. Logs
are under `<runs-root>/desktop`: `startup.log`, `backend.log`, and `browser.log`.
For import/interpreter failures before logs exist, use the package CMD entry
from a terminal and check `BRAINWORKFLOW_PYTHON`.

Windows quoting has two distinct boundaries: WScript treats backslashes
literally, while Python uses CRT argument parsing and needs trailing
backslashes escaped inside quotes. Do not reuse Python list2cmdline for WScript
arguments. Programmatic CMD invocation needs a native backslash executable
path and an outer quote pair around its `/d /s /c` command. Both CMD entries
disable delayed expansion to preserve `!` in paths. Both VBS process boundaries
repair SystemRoot/windir before spawning children without clearing other
environment variables.

### Verification Evidence

- RED: original desktop suite reproduced three launcher failures: root VBS
  returned without fake bootstrap output; both CMD invocations had syntax errors.
- Root cause: broken Windows roots were inherited by the nested script host;
  the CMD test invocation used forward slashes and lacked outer CMD quoting.
- Additional RED cases caught doubled trailing backslashes in root VBS,
  inherited delayed expansion dropping `!`, and missing root console diagnostics.
- GREEN: `python -m unittest tests.test_desktop -q`, 16 tests passed. The actual
  four scripts run a fake module from a path containing spaces and `&`; assertions
  check exact arguments (including `!` and trailing backslash), cwd, environment
  repair/preservation, synchronous completion and nonzero bootstrap diagnostics.
- Native app-only smoke: explicit installed Edge and current Python, isolated
  `.desktop-launch-smoke-20260923` knowledge/runs under the package. Root VBS
  launch and repeat launch returned 0; tagged visible app window found; dashboard
  HTTP 200 (12,205 bytes); health `server_revision=console-sse-v2`, all roots match.
  One backend PID 80208 served port 63369. Closing the tagged HWND with WM_CLOSE
  left health available; reopening returned 0 and reused the same backend PID.
- No workflow action or WQB call was made; no `run_state.json` was created.
  Smoke-owned browser/backend processes were stopped after verification. Logs
  and the isolated browser profile are retained locally, not delivery artifacts.
- Limits: no screenshot/visual-layout acceptance or full runtime acceptance in
  this bounded task. The shell lacked browser-discovery environment variables,
  so the smoke used an explicit browser override. An initial .NET
  CloseMainWindow attempt returned false; the tagged-HWND WM_CLOSE check passed.

This bounded continuation leaves `desktop.py`, the package VBS and the server
health contract unchanged. Other runtime/Console work remains separately owned.

Task C implementation contract, 2026-09-05. Controller owns the main plan,
todo and milestone; this file records only the desktop handoff.

## Task C Resume Plan (2026-09-19)

- Approved scope: preserve the existing desktop implementation and its 13
  passing tests; do not touch Console, CLI, worker, shared plan/todo/milestone.
- Add RED regressions for health revision validation and executable Windows
  launchers, then make the smallest fixes with apply_patch.
- Provide workspace and package-relative double-click entries, Python
  discovery, repaired Windows child environment and visible bootstrap errors.
- Verify real local backend identity/reuse, competing launch locks, app-mode
  opening and close/reopen where native access permits. No workflow action,
  live platform call, credential access, commit or push is authorized.
- Run desktop tests and the non-live suite with child SystemRoot/windir set
  to C:/Windows; record failures owned by other tasks without editing them.
- Current baseline: `python -m unittest tests.test_desktop -v`: 13 passed.

## Console Hook Required From Controller / Task B

Implement `GET /api/health` before any dashboard/state loading. Respond 200
with JSON containing:

```json
{
  "app": "BrainWorkflow",
  "workflow_root": "absolute resolved package directory",
  "knowledge_root": "absolute resolved knowledge directory",
  "runs_root": "absolute resolved runs directory",
  "server_revision": "nonempty server protocol revision",
  "code_revision": "loaded source SHA256 fingerprint"
}
```

The desktop launcher reuses a backend only when the app and all three roots
match, server_revision is nonempty, and code_revision equals the launcher's loaded
source fingerprint. Extra fields are allowed. This endpoint must
not load knowledge, scan research runs, start jobs, or call the platform.
Old Console instances without this endpoint are treated as foreign ports.
Task C does not edit `console_server.py` or `cli.py`.

## Implementation Sequence

Local acceptance (2026-10-10): workspace-root VBS opened a visible app against isolated smoke roots. A second launch reused the backend; closing the owned window kept the backend alive and reopening reused it. Only verified smoke-owned processes were cleaned up; no research run or platform call was created. Final regression passed 1041 tests including loaded-code compatibility. This verifies app mode, not a native installer or live research.

1. RED: test environment repair, command/path construction, installed browser
   discovery, identity validation, foreign-port refusal, and OS lock ownership.
2. GREEN: add the standard-library desktop bootstrap, backend lifetime lock,
   hidden launch, visible errors and installed Edge/Chrome app-mode entry.
3. Verify concurrent launches and backend reuse locally, without platform calls.
4. Document the double-click entry and an actual Windows window verification
   procedure, distinguishing automated evidence from manual acceptance.
