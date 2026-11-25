"""Background process options; diagnostic decoding is independent of strict JSON file validation."""
import os
import subprocess


def background_process_options(*, text: bool = False) -> dict:
    """Input: text bool. Output: subprocess kwargs; hide Windows consoles and decode diagnostic streams as UTF-8."""
    options = dict(creationflags=subprocess.CREATE_NO_WINDOW) if os.name == 'nt' else {}
    if text:
        options.update(encoding='utf-8', errors='replace')
    return options
