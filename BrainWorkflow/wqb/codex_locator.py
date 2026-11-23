"""Bounded maintenance executable resolution; no model invocation or repair authority."""
import json
import os
from pathlib import Path
import subprocess
from uuid import UUID

DISCOVERY_TIMEOUT_SECONDS = 5
MAX_DISCOVERY_OUTPUT_BYTES = 32768


def _installed_codex() -> dict:
    """Input: current Windows package registration. Output: exact installed CLI path or distinct bounded discovery error."""
    empty = dict(executable=None, source='registered_package', error='codex_not_found')
    if os.name != 'nt':
        return empty
    from wqb.desktop import child_environment, hidden_process_options
    env = child_environment()
    env['SystemDrive'] = Path(env['SystemRoot']).drive
    env['PSModuleAnalysisCachePath'] = 'NUL'
    shell = Path(env['SystemRoot'])/'System32/WindowsPowerShell/v1.0/powershell.exe'
    if not shell.is_file():
        return empty
    command = ('[Console]::OutputEncoding=[System.Text.UTF8Encoding]::new($false); '
               '@((Get-AppxPackage -Name OpenAI.Codex).InstallLocation) | ConvertTo-Json -Compress')
    try:
        process = subprocess.run([str(shell), '-NoProfile', '-NonInteractive', '-Command', command],
            capture_output=True, encoding='utf-8', errors='strict', timeout=DISCOVERY_TIMEOUT_SECONDS,
            env=env, check=False, **hidden_process_options())
        if process.returncode != 0 or len(process.stdout.encode()) > MAX_DISCOVERY_OUTPUT_BYTES:
            return {**empty, 'error': 'codex_discovery_failed'}
        locations = json.loads(process.stdout) if process.stdout.strip() else []
        if isinstance(locations, str):
            locations = [locations]
        if not isinstance(locations, list) or any(not isinstance(value, str) for value in locations):
            return {**empty, 'error': 'codex_discovery_failed'}
        candidates = set()
        for location in locations:
            path = Path(location)/'app/resources/codex.exe'
            if path.is_absolute() and path.is_file():
                candidates.add(str(path))
        if len(candidates) > 1:
            return {**empty, 'error': 'codex_installation_ambiguous'}
        return dict(executable=next(iter(candidates)), source='registered_package', error='') if candidates else empty
    except subprocess.TimeoutExpired:
        return {**empty, 'error': 'codex_discovery_timeout'}
    except (OSError, ValueError, UnicodeError):
        return {**empty, 'error': 'codex_discovery_failed'}


def resolve_codex_executable(config: dict, *, path_lookup) -> dict:
    """Input: optional executable config/PATH lookup. Output: CLI discovery without a maintenance-channel dependency."""
    result = dict(executable=None, source='', error='codex_not_found')
    explicit = config.get('codex_executable')
    if explicit is not None:
        if not isinstance(explicit, str):
            return {**result, 'error': 'codex_executable_invalid'}
        path = Path(explicit)
        if not path.is_absolute() or not path.is_file() or path.name.lower() != 'codex.exe':
            return {**result, 'error': 'codex_executable_invalid'}
        return {**result, 'executable': str(path), 'source': 'configured', 'error': ''}
    executable = path_lookup('codex')
    if executable:
        return {**result, 'executable': executable, 'source': 'path', 'error': ''}
    return {**result, **_installed_codex()}


def resolve_notification_target(config: dict, *, path_lookup) -> dict:
    """Input: maintenance channel dict/PATH lookup callable. Output: channel, executable and specific resolution evidence."""
    thread = str(config.get('thread_id', '')) if isinstance(config, dict) else ''
    result = dict(thread_id=thread, executable=None, source='', error='channel_not_configured')
    try:
        UUID(thread)
    except ValueError:
        return result
    return {**result, **resolve_codex_executable(config, path_lookup=path_lookup)}
