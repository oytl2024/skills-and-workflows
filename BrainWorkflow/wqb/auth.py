import os


def _read_windows_user_env_var(name: str) -> str:
    """Input: env var name (str). Output: value (str). Read Windows user-level env from registry."""
    if os.name != "nt":
        return ""
    try:
        import winreg
    except ImportError:
        return ""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
            value, _ = winreg.QueryValueEx(key, name)
    except OSError:
        return ""
    return str(value).strip()


def load_credentials() -> tuple[str, str]:
    """Input: env vars. Output: username/password tuple. Read process env, then Windows user env."""
    username = (
        os.environ.get("WQB_USERNAME", "").strip()
        or _read_windows_user_env_var("WQB_USERNAME")
    ).strip()
    password = (
        os.environ.get("WQB_PASSWORD", "").strip()
        or _read_windows_user_env_var("WQB_PASSWORD")
    ).strip()
    if not username or not password:
        raise RuntimeError("WQB_USERNAME and WQB_PASSWORD must be set")
    return username, password
