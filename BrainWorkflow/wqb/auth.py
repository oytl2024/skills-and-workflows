import os


def load_credentials() -> tuple[str, str]:
    """Input: environment variables. Output: username/password tuple. Fail if credentials are missing."""
    username = os.environ.get("WQB_USERNAME", "").strip()
    password = os.environ.get("WQB_PASSWORD", "").strip()
    if not username or not password:
        raise RuntimeError("WQB_USERNAME and WQB_PASSWORD must be set")
    return username, password
