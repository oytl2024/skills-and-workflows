from pathlib import Path
from typing import Any

import yaml

DEFAULT_CONFIG = {
    "instrument_type": "EQUITY",
    "language": "FASTEXPR",
    "neutralization": "SUBINDUSTRY",
    "decay": 4,
    "truncation": 0.08,
    "pasteurization": "ON",
    "unit_handling": "VERIFY",
    "nan_handling": "OFF",
    "max_alphas_per_round": 50,
    "max_rounds": 5,
    "stop_after_first_candidate": True,
    "request_timeout_seconds": 30,
    "max_retries": 4,
    "base_backoff_seconds": 3,
    "run_root": "runs",
    "ordinary_probe_count": 3,
    "power_pool_operator_limit": 8,
    "power_pool_field_limit": 3,
}

REQUIRED_CONFIG_KEYS = ["region", "universe", "delay"]
ON_OFF_CONFIG_KEYS = ["pasteurization", "nan_handling"]


def normalize_on_off(value: Any) -> str:
    """Input: bool or string. Output: ON/OFF string. Normalize YAML boolean-like platform toggles."""
    if isinstance(value, bool):
        return "ON" if value else "OFF"
    return str(value).upper()


def load_config(
    path: str | Path, overrides: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Input: YAML path as str|Path and optional overrides dict; output: config dict. Load, merge defaults, validate required keys, and normalize numeric fields."""
    config_path = Path(path)
    loaded_config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if not isinstance(loaded_config, dict):
        raise ValueError("config root must be a mapping")

    config = dict(DEFAULT_CONFIG)
    config.update(loaded_config)

    if overrides:
        config.update({key: value for key, value in overrides.items() if value is not None})

    missing_keys = [
        key
        for key in REQUIRED_CONFIG_KEYS
        if key not in config or config[key] is None or config[key] == ""
    ]
    if missing_keys:
        raise ValueError(f"missing required config keys: {', '.join(missing_keys)}")

    for key in ["delay", "max_alphas_per_round", "max_rounds"]:
        config[key] = int(config[key])
    for key in ON_OFF_CONFIG_KEYS:
        if key in config:
            config[key] = normalize_on_off(config[key])

    return config
