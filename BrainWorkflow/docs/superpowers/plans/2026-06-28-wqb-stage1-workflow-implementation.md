# WorldQuant Brain Stage 1 Workflow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a maintainable Python CLI workflow that generates, simulates, checks, optimizes, and records WorldQuant Brain Alpha candidates, stopping only when a hard-check-passing candidate is found or the configured Stage 1 budget is exhausted.

**Architecture:** Implement a small `wqb` package with clear API, model, generator, simulator, checker, optimizer, recorder, and CLI boundaries. Use local YAML config, JSONL/CSV run artifacts, conservative request retry/backoff, and rule-driven optimization so the Stage 1 rescue workflow can evolve into a long-term research system.

**Tech Stack:** Python 3, `requests`, `PyYAML`, standard-library `dataclasses`, `unittest`, `argparse`, `csv`, `json`, `hashlib`, and PowerShell/Bash-compatible launcher scripts.

---

## Current Constraints

- The workspace path is `C:\Users\oytl\Desktop\pyproject\brain`.
- `PyYAML` is installed.
- `pytest` is not installed, so Stage 1 tests must use standard-library `unittest`.
- The `.git` directory exists but is empty or invalid; `git status` fails. Commit steps are documented as optional checkpoints for a future valid git repository.
- Credentials must come only from `WQB_USERNAME` and `WQB_PASSWORD`.
- Do not call any submit endpoint.

## File Structure

Create:

- `wqb/__init__.py`: Package marker and version string.
- `wqb/models.py`: Dataclasses for settings, generated candidates, simulation records, check records, optimization actions, and run config.
- `wqb/config.py`: YAML config loader and CLI override merge.
- `wqb/auth.py`: Environment-variable credential loading.
- `wqb/client.py`: WorldQuant Brain HTTP client with retries, timeout, `Retry-After`, 429 backoff, and auth refresh.
- `wqb/knowledge.py`: Snapshot platform search, tutorial, FAQ, message, video, event, competition, and Power Pool board metadata.
- `wqb/data_catalog.py`: Data-set and data-field retrieval, filtering, and field-pool construction.
- `wqb/expression.py`: Expression hashing, operator counting, and data-field counting.
- `wqb/generator.py`: Rule-based expression and simulation payload generation.
- `wqb/simulator.py`: Simulation submission and polling.
- `wqb/checker.py`: Alpha detail and `/check` classification.
- `wqb/optimizer.py`: Failure-to-action mapping and next-round candidate generation.
- `wqb/recorder.py`: JSONL, CSV, Markdown summary, and resume support.
- `wqb/cli.py`: `dry-run`, `smoke`, and `run-stage1` commands.
- `configs/stage1_usa_d1.yaml`: Default Stage 1 config.
- `run_stage1.sh`: Bash launcher with editable hyperparameters.
- `run_stage1.ps1`: Windows PowerShell launcher with the same hyperparameters.
- `tests/__init__.py`: Test package marker.
- `tests/test_config.py`: Config tests.
- `tests/test_expression.py`: Expression complexity tests.
- `tests/test_checker.py`: Check classification tests.
- `tests/test_optimizer.py`: Optimization rule tests.
- `tests/test_recorder.py`: Recorder and resume tests.
- `tests/test_generator.py`: Payload generation tests.

Modify:

- `todo.md`: Append implementation-plan status and later implementation progress.
- `docs/superpowers/specs/2026-06-28-wqb-stage1-workflow-design.md`: Only if implementation discovers a spec-level correction is needed.

Do not modify old scripts (`sign_in.py`, `get_data.py`, `alpha_settings.py`, `multisimulate.py`, `results.py`, `correlation_check.py`) during Stage 1 implementation. They are legacy references.

## Task 1: Scaffold Package, Config, and Test Runner

**Files:**
- Create: `wqb/__init__.py`
- Create: `wqb/config.py`
- Create: `configs/stage1_usa_d1.yaml`
- Create: `tests/__init__.py`
- Create: `tests/test_config.py`
- Modify: `todo.md`

- [ ] **Step 1: Write the config loader test**

Create `tests/test_config.py`:

```python
import tempfile
import unittest
from pathlib import Path

from wqb.config import load_config


class ConfigTests(unittest.TestCase):
    def test_load_config_reads_yaml_and_applies_defaults(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "config.yaml"
            path.write_text(
                "\n".join(
                    [
                        "region: USA",
                        "universe: TOP3000",
                        "delay: 1",
                        "max_alphas_per_round: 7",
                    ]
                ),
                encoding="utf-8",
            )

            config = load_config(path)

            self.assertEqual(config["region"], "USA")
            self.assertEqual(config["universe"], "TOP3000")
            self.assertEqual(config["delay"], 1)
            self.assertEqual(config["max_alphas_per_round"], 7)
            self.assertEqual(config["instrument_type"], "EQUITY")
            self.assertEqual(config["language"], "FASTEXPR")

    def test_load_config_rejects_missing_required_keys(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "config.yaml"
            path.write_text("region: USA\n", encoding="utf-8")

            with self.assertRaises(ValueError) as err:
                load_config(path)

            self.assertIn("missing required config keys", str(err.exception))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the failing config test**

Run:

```bash
python -m unittest tests.test_config -v
```

Expected: fail because `wqb.config` does not exist.

- [ ] **Step 3: Create package marker**

Create `wqb/__init__.py`:

```python
__version__ = "0.1.0"
```

- [ ] **Step 4: Implement config loader**

Create `wqb/config.py`:

```python
from pathlib import Path
from typing import Any

import yaml


DEFAULT_CONFIG: dict[str, Any] = {
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


def load_config(path: str | Path, overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    """Input: YAML path and optional override dict. Output: config dict. Load and validate Stage 1 settings."""
    config_path = Path(path)
    with config_path.open("r", encoding="utf-8") as file:
        loaded = yaml.safe_load(file) or {}
    if not isinstance(loaded, dict):
        raise ValueError("config root must be a mapping")

    config = dict(DEFAULT_CONFIG)
    config.update(loaded)
    if overrides:
        config.update({key: value for key, value in overrides.items() if value is not None})

    missing = [key for key in REQUIRED_CONFIG_KEYS if key not in config or config[key] in ("", None)]
    if missing:
        raise ValueError(f"missing required config keys: {', '.join(missing)}")

    config["delay"] = int(config["delay"])
    config["max_alphas_per_round"] = int(config["max_alphas_per_round"])
    config["max_rounds"] = int(config["max_rounds"])
    return config
```

- [ ] **Step 5: Create default config**

Create `configs/stage1_usa_d1.yaml`:

```yaml
region: USA
universe: TOP3000
delay: 1
instrument_type: EQUITY
language: FASTEXPR
neutralization: SUBINDUSTRY
decay: 4
truncation: 0.08
pasteurization: ON
unit_handling: VERIFY
nan_handling: OFF
max_alphas_per_round: 50
max_rounds: 5
stop_after_first_candidate: true
ordinary_probe_count: 3
power_pool_operator_limit: 8
power_pool_field_limit: 3
request_timeout_seconds: 30
max_retries: 4
base_backoff_seconds: 3
run_root: runs
power_pool_theme_query: "USA/D1 Fast Datasets Power Pool June`26"
knowledge_queries:
  - Power Pool
  - Alpha Submit Criteria
  - submission criteria
  - Sharpe Fitness
  - turnover
  - neutralization
  - truncation
  - self correlation
  - prod correlation
  - data diversity
  - robust universe
  - Fast D1
  - fast datasets
```

- [ ] **Step 6: Add test package marker**

Create `tests/__init__.py`:

```python
```

- [ ] **Step 7: Run config tests**

Run:

```bash
python -m unittest tests.test_config -v
```

Expected: pass.

- [ ] **Step 8: Update `todo.md`**

Append a progress bullet:

```markdown
- 2026-06-28：开始按实施计划创建 Stage 1 CLI 工作流骨架，采用 `unittest` 避免额外安装 pytest。
```

- [ ] **Step 9: Optional checkpoint**

If this folder is later converted into a valid git repository, commit:

```bash
git add wqb/__init__.py wqb/config.py configs/stage1_usa_d1.yaml tests/__init__.py tests/test_config.py todo.md
git commit -m "chore: scaffold stage1 config loader"
```

Expected now: skip commit because `git status` fails in the current workspace.

## Task 2: Models and Expression Utilities

**Files:**
- Create: `wqb/models.py`
- Create: `wqb/expression.py`
- Create: `tests/test_expression.py`
- Test: `python -m unittest tests.test_expression -v`

- [ ] **Step 1: Write expression tests**

Create `tests/test_expression.py`:

```python
import unittest

from wqb.expression import count_data_fields, count_operators, expression_hash, is_power_pool_complexity_ok


class ExpressionTests(unittest.TestCase):
    def test_expression_hash_is_stable(self):
        self.assertEqual(expression_hash("rank(close)"), expression_hash(" rank(close) "))

    def test_count_operators_ignores_backfill_for_power_pool(self):
        expression = "rank(ts_mean(ts_backfill(news_score, 20), 5))"
        counts = count_operators(expression)
        self.assertEqual(counts["rank"], 1)
        self.assertEqual(counts["ts_mean"], 1)
        self.assertEqual(counts["ts_backfill"], 1)

    def test_count_data_fields_excludes_grouping_fields(self):
        expression = "group_neutralize(rank(news_score), subindustry) + rank(volume)"
        fields = count_data_fields(expression, known_fields={"news_score", "volume", "subindustry"})
        self.assertEqual(fields, {"news_score", "volume"})

    def test_power_pool_complexity_passes_simple_expression(self):
        result = is_power_pool_complexity_ok(
            "rank(ts_mean(news_score, 5))",
            known_fields={"news_score"},
            operator_limit=8,
            field_limit=3,
        )
        self.assertTrue(result.ok)
        self.assertEqual(result.operator_count, 2)
        self.assertEqual(result.field_count, 1)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run failing expression tests**

Run:

```bash
python -m unittest tests.test_expression -v
```

Expected: fail because `wqb.expression` does not exist.

- [ ] **Step 3: Implement models**

Create `wqb/models.py`:

```python
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class AlphaCandidate:
    expression: str
    settings: dict[str, Any]
    generation: int
    parent_hash: str | None = None
    action: str = "seed"
    tags: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ComplexityResult:
    ok: bool
    operator_count: int
    field_count: int
    operators: dict[str, int]
    fields: set[str]
    reasons: list[str]


@dataclass(frozen=True)
class CheckItem:
    name: str
    result: str
    value: Any = None
    limit: Any = None


@dataclass(frozen=True)
class CheckSummary:
    alpha_id: str
    hard_pass: bool
    failed: list[CheckItem]
    warnings: list[CheckItem]
    pending: list[CheckItem]
    metrics: dict[str, Any]


@dataclass(frozen=True)
class OptimizationAction:
    parent_hash: str
    reason: str
    action_type: str
    details: dict[str, Any]
```

- [ ] **Step 4: Implement expression utilities**

Create `wqb/expression.py`:

```python
import hashlib
import re

from wqb.models import ComplexityResult


GROUPING_FIELDS = {"country", "industry", "subindustry", "currency", "market", "sector", "exchange"}
BACKFILL_OPERATORS_EXCLUDED_FROM_POWER_POOL = {"ts_backfill", "group_backfill"}
OPERATOR_RE = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*\(")


def normalize_expression(expression: str) -> str:
    """Input: expression string. Output: normalized string. Collapse whitespace for stable hashing."""
    return re.sub(r"\s+", " ", expression.strip())


def expression_hash(expression: str) -> str:
    """Input: expression string. Output: sha256 hex digest. Identify equivalent generated expressions."""
    normalized = normalize_expression(expression)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def count_operators(expression: str) -> dict[str, int]:
    """Input: expression string. Output: operator count dict. Count function-like tokens."""
    counts: dict[str, int] = {}
    for match in OPERATOR_RE.finditer(expression):
        name = match.group(1)
        counts[name] = counts.get(name, 0) + 1
    return counts


def count_data_fields(expression: str, known_fields: set[str]) -> set[str]:
    """Input: expression and known fields. Output: data fields used, excluding grouping fields."""
    used: set[str] = set()
    for field in known_fields:
        if field in GROUPING_FIELDS:
            continue
        if re.search(rf"\b{re.escape(field)}\b", expression):
            used.add(field)
    return used


def is_power_pool_complexity_ok(
    expression: str,
    known_fields: set[str],
    operator_limit: int,
    field_limit: int,
) -> ComplexityResult:
    """Input: expression, known fields, limits. Output: complexity result for Power Pool eligibility."""
    operators = count_operators(expression)
    operator_count = sum(
        count for name, count in operators.items() if name not in BACKFILL_OPERATORS_EXCLUDED_FROM_POWER_POOL
    )
    fields = count_data_fields(expression, known_fields)
    reasons: list[str] = []
    if operator_count > operator_limit:
        reasons.append(f"operator_count {operator_count} exceeds {operator_limit}")
    if len(fields) > field_limit:
        reasons.append(f"field_count {len(fields)} exceeds {field_limit}")
    return ComplexityResult(
        ok=not reasons,
        operator_count=operator_count,
        field_count=len(fields),
        operators=operators,
        fields=fields,
        reasons=reasons,
    )
```

- [ ] **Step 5: Run expression tests**

Run:

```bash
python -m unittest tests.test_expression -v
```

Expected: pass.

- [ ] **Step 6: Optional checkpoint**

If git becomes valid:

```bash
git add wqb/models.py wqb/expression.py tests/test_expression.py
git commit -m "feat: add alpha models and expression utilities"
```

Expected now: skip commit.

## Task 3: Auth and API Client

**Files:**
- Create: `wqb/auth.py`
- Create: `wqb/client.py`
- Test through a small inline fake-session script, then live smoke later.

- [ ] **Step 1: Implement credential loader**

Create `wqb/auth.py`:

```python
import os


def load_credentials() -> tuple[str, str]:
    """Input: environment variables. Output: username/password tuple. Fail if credentials are missing."""
    username = os.environ.get("WQB_USERNAME", "").strip()
    password = os.environ.get("WQB_PASSWORD", "").strip()
    if not username or not password:
        raise RuntimeError("WQB_USERNAME and WQB_PASSWORD must be set")
    return username, password
```

- [ ] **Step 2: Implement API client**

Create `wqb/client.py`:

```python
import time
from typing import Any

import requests

from wqb.auth import load_credentials


BASE_URL = "https://api.worldquantbrain.com"


class WQBClient:
    def __init__(
        self,
        timeout_seconds: int = 30,
        max_retries: int = 4,
        base_backoff_seconds: int = 3,
        session: requests.Session | None = None,
    ) -> None:
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.base_backoff_seconds = base_backoff_seconds
        self.session = session or requests.Session()
        self.authenticated = False

    def authenticate(self) -> None:
        """Input: env credentials. Output: authenticated session. Authenticate against WorldQuant Brain."""
        username, password = load_credentials()
        self.session.auth = (username, password)
        response = self.session.post(f"{BASE_URL}/authentication", timeout=self.timeout_seconds)
        response.raise_for_status()
        self.authenticated = True

    def request(self, method: str, path: str, **kwargs: Any) -> requests.Response:
        """Input: HTTP method/path. Output: response. Retry transient failures and respect platform pacing."""
        if not self.authenticated:
            self.authenticate()
        url = path if path.startswith("http") else f"{BASE_URL}{path}"
        for attempt in range(self.max_retries + 1):
            response = self.session.request(method, url, timeout=self.timeout_seconds, **kwargs)
            retry_after = response.headers.get("Retry-After")
            if retry_after:
                time.sleep(float(retry_after))
                continue
            if response.status_code == 401 and attempt < self.max_retries:
                self.authenticated = False
                self.authenticate()
                continue
            if response.status_code == 429 and attempt < self.max_retries:
                time.sleep(self.base_backoff_seconds * (attempt + 1))
                continue
            if 500 <= response.status_code < 600 and attempt < self.max_retries:
                time.sleep(self.base_backoff_seconds * (attempt + 1))
                continue
            return response
        return response

    def get_json(self, path: str) -> Any:
        """Input: API path. Output: parsed JSON. Fetch JSON with retry handling."""
        response = self.request("GET", path)
        response.raise_for_status()
        return response.json()

    def post_json(self, path: str, payload: Any) -> requests.Response:
        """Input: API path and JSON payload. Output: response. POST JSON with retry handling."""
        response = self.request("POST", path, json=payload)
        response.raise_for_status()
        return response

    def options_json(self, path: str) -> Any:
        """Input: API path. Output: parsed OPTIONS JSON. Read API metadata for allowed filters."""
        response = self.request("OPTIONS", path)
        response.raise_for_status()
        return response.json()
```

- [ ] **Step 3: Run syntax check**

Run:

```bash
python -m py_compile wqb/auth.py wqb/client.py
```

Expected: no output and exit code 0.

- [ ] **Step 4: Verify credentials are not printed**

Run:

```bash
python -c "from wqb.auth import load_credentials; u,p=load_credentials(); print(bool(u), bool(p))"
```

Expected: `True True`, no actual credential value.

- [ ] **Step 5: Optional checkpoint**

If git becomes valid:

```bash
git add wqb/auth.py wqb/client.py
git commit -m "feat: add WorldQuant Brain client"
```

Expected now: skip commit.

## Task 4: Recorder and Resume Support

**Files:**
- Create: `wqb/recorder.py`
- Create: `tests/test_recorder.py`
- Test: `python -m unittest tests.test_recorder -v`

- [ ] **Step 1: Write recorder tests**

Create `tests/test_recorder.py`:

```python
import csv
import json
import tempfile
import unittest
from pathlib import Path

from wqb.recorder import RunRecorder


class RecorderTests(unittest.TestCase):
    def test_jsonl_append_and_seen_hashes(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            recorder = RunRecorder(Path(tmpdir))
            recorder.append_jsonl("all_alphas.jsonl", {"expression_hash": "abc", "status": "SIMULATED"})
            recorder.append_jsonl("all_alphas.jsonl", {"expression_hash": "def", "status": "FAILED"})

            self.assertEqual(recorder.seen_expression_hashes(), {"abc", "def"})

    def test_candidates_csv_written_with_headers(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            recorder = RunRecorder(Path(tmpdir))
            recorder.write_candidates(
                [
                    {
                        "alpha_id": "abc123",
                        "expression_hash": "hash1",
                        "sharpe": 1.8,
                        "fitness": 1.2,
                        "turnover": 0.22,
                    }
                ]
            )
            with (Path(tmpdir) / "candidates.csv").open("r", encoding="utf-8", newline="") as file:
                rows = list(csv.DictReader(file))

            self.assertEqual(rows[0]["alpha_id"], "abc123")
            self.assertEqual(rows[0]["expression_hash"], "hash1")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run failing recorder tests**

Run:

```bash
python -m unittest tests.test_recorder -v
```

Expected: fail because `wqb.recorder` does not exist.

- [ ] **Step 3: Implement recorder**

Create `wqb/recorder.py`:

```python
import csv
import json
from pathlib import Path
from typing import Any


class RunRecorder:
    def __init__(self, run_dir: str | Path) -> None:
        self.run_dir = Path(run_dir)
        self.run_dir.mkdir(parents=True, exist_ok=True)

    def append_jsonl(self, filename: str, record: dict[str, Any]) -> None:
        """Input: filename and JSON-serializable record. Output: none. Append one run event."""
        path = self.run_dir / filename
        with path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")

    def read_jsonl(self, filename: str) -> list[dict[str, Any]]:
        """Input: filename. Output: list of records. Read a run JSONL artifact."""
        path = self.run_dir / filename
        if not path.exists():
            return []
        records: list[dict[str, Any]] = []
        with path.open("r", encoding="utf-8") as file:
            for line in file:
                if line.strip():
                    records.append(json.loads(line))
        return records

    def seen_expression_hashes(self) -> set[str]:
        """Input: existing run records. Output: expression hashes. Support resume without duplicate simulations."""
        hashes: set[str] = set()
        for record in self.read_jsonl("all_alphas.jsonl"):
            expression_hash = record.get("expression_hash")
            if expression_hash:
                hashes.add(str(expression_hash))
        return hashes

    def write_candidates(self, rows: list[dict[str, Any]]) -> None:
        """Input: candidate rows. Output: candidates.csv. Persist hard-check-passing Alphas."""
        path = self.run_dir / "candidates.csv"
        fieldnames = ["alpha_id", "expression_hash", "sharpe", "fitness", "turnover", "returns", "warnings"]
        with path.open("w", encoding="utf-8", newline="") as file:
            writer = csv.DictWriter(file, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            for row in rows:
                writer.writerow(row)

    def write_markdown(self, filename: str, content: str) -> None:
        """Input: filename and markdown content. Output: markdown file. Save run summaries."""
        path = self.run_dir / filename
        path.write_text(content, encoding="utf-8")
```

- [ ] **Step 4: Run recorder tests**

Run:

```bash
python -m unittest tests.test_recorder -v
```

Expected: pass.

- [ ] **Step 5: Optional checkpoint**

If git becomes valid:

```bash
git add wqb/recorder.py tests/test_recorder.py
git commit -m "feat: add run recorder"
```

Expected now: skip commit.

## Task 5: Checker Classification

**Files:**
- Create: `wqb/checker.py`
- Create: `tests/test_checker.py`
- Test: `python -m unittest tests.test_checker -v`

- [ ] **Step 1: Write checker tests**

Create `tests/test_checker.py`:

```python
import unittest

from wqb.checker import classify_check_response


class CheckerTests(unittest.TestCase):
    def test_hard_pass_when_all_hard_checks_pass_and_warnings_exist(self):
        response = {
            "is": {
                "checks": [
                    {"name": "LOW_SHARPE", "result": "PASS", "limit": 1.25},
                    {"name": "LOW_FITNESS", "result": "PASS", "limit": 1.0},
                    {"name": "MATCHES_THEMES", "result": "WARNING"},
                ]
            }
        }
        metrics = {"sharpe": 1.6, "fitness": 1.1, "turnover": 0.2}

        summary = classify_check_response("alpha1", response, metrics)

        self.assertTrue(summary.hard_pass)
        self.assertEqual(len(summary.warnings), 1)

    def test_pending_is_not_hard_pass(self):
        response = {"is": {"checks": [{"name": "SELF_CORRELATION", "result": "PENDING"}]}}

        summary = classify_check_response("alpha1", response, {})

        self.assertFalse(summary.hard_pass)
        self.assertEqual(summary.pending[0].name, "SELF_CORRELATION")

    def test_failed_hard_check_blocks_candidate(self):
        response = {"is": {"checks": [{"name": "LOW_SHARPE", "result": "FAIL", "limit": 1.25}]}}

        summary = classify_check_response("alpha1", response, {"sharpe": 0.8})

        self.assertFalse(summary.hard_pass)
        self.assertEqual(summary.failed[0].name, "LOW_SHARPE")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run failing checker tests**

Run:

```bash
python -m unittest tests.test_checker -v
```

Expected: fail because `wqb.checker` does not exist.

- [ ] **Step 3: Implement checker**

Create `wqb/checker.py`:

```python
from typing import Any

from wqb.models import CheckItem, CheckSummary


WARNING_RESULTS = {"WARNING"}
PASS_RESULTS = {"PASS"}
PENDING_RESULTS = {"PENDING"}


def classify_check_response(alpha_id: str, check_response: dict[str, Any], metrics: dict[str, Any]) -> CheckSummary:
    """Input: alpha id, check JSON, metrics. Output: classified check summary for candidate gating."""
    checks = check_response.get("is", {}).get("checks", [])
    failed: list[CheckItem] = []
    warnings: list[CheckItem] = []
    pending: list[CheckItem] = []

    for item in checks:
        name = str(item.get("name", "UNKNOWN"))
        result = str(item.get("result", "UNKNOWN")).upper()
        check_item = CheckItem(
            name=name,
            result=result,
            value=item.get("value"),
            limit=item.get("limit") or item.get("threshold") or item.get("cutoff"),
        )
        if result in PASS_RESULTS:
            continue
        if result in WARNING_RESULTS:
            warnings.append(check_item)
            continue
        if result in PENDING_RESULTS:
            pending.append(check_item)
            continue
        failed.append(check_item)

    hard_pass = not failed and not pending
    return CheckSummary(
        alpha_id=alpha_id,
        hard_pass=hard_pass,
        failed=failed,
        warnings=warnings,
        pending=pending,
        metrics=metrics,
    )


def fetch_check_summary(client, alpha_id: str) -> CheckSummary:
    """Input: WQB client and alpha id. Output: classified check summary. Fetch alpha detail and check JSON."""
    alpha = client.get_json(f"/alphas/{alpha_id}")
    metrics = alpha.get("is", {}) if isinstance(alpha, dict) else {}
    check_response = client.get_json(f"/alphas/{alpha_id}/check")
    return classify_check_response(alpha_id, check_response, metrics)
```

- [ ] **Step 4: Run checker tests**

Run:

```bash
python -m unittest tests.test_checker -v
```

Expected: pass.

- [ ] **Step 5: Optional checkpoint**

If git becomes valid:

```bash
git add wqb/checker.py tests/test_checker.py
git commit -m "feat: classify alpha checks"
```

Expected now: skip commit.

## Task 6: Data Catalog and Knowledge Snapshot

**Files:**
- Create: `wqb/knowledge.py`
- Create: `wqb/data_catalog.py`
- Test through dry-run and live smoke because these modules depend on the platform API.

- [ ] **Step 1: Implement knowledge snapshot**

Create `wqb/knowledge.py`:

```python
from typing import Any
from urllib.parse import quote


DETAIL_PATHS = {
    "tutorialPage": "/tutorial-pages/{id}",
    "faq": "/faqs/{id}",
    "message": "/messages/{id}",
    "video": "/videos/{id}",
}


def fetch_knowledge_snapshot(client, queries: list[str]) -> dict[str, Any]:
    """Input: WQB client and query list. Output: knowledge snapshot dict. Save source material for this run."""
    snapshot: dict[str, Any] = {"queries": {}, "details": {}, "power_pool_boards": None}
    for query in queries:
        result = client.get_json(f"/search?query={quote(query)}")
        snapshot["queries"][query] = result
        for group, template in DETAIL_PATHS.items():
            results = result.get(group, {}).get("results", []) if isinstance(result.get(group), dict) else []
            for item in results[:3]:
                item_id = item.get("id")
                if not item_id:
                    continue
                key = f"{group}:{item_id}"
                if key not in snapshot["details"]:
                    snapshot["details"][key] = client.get_json(template.format(id=item_id))

    snapshot["events"] = client.get_json("/events?limit=20&offset=0")
    snapshot["competitions"] = client.get_json("/competitions?limit=20&offset=0")
    snapshot["power_pool_boards"] = client.options_json("/consultant/boards/power-pool")
    return snapshot
```

- [ ] **Step 2: Implement data catalog**

Create `wqb/data_catalog.py`:

```python
from typing import Any


def fetch_data_fields(
    client,
    instrument_type: str,
    region: str,
    delay: int,
    universe: str,
    dataset_id: str = "",
    search: str = "",
    limit: int = 50,
    max_records: int = 300,
) -> list[dict[str, Any]]:
    """Input: WQB client and field filters. Output: data-field records. Fetch a bounded field pool."""
    fields: list[dict[str, Any]] = []
    offset = 0
    while offset < max_records:
        path = (
            f"/data-fields?instrumentType={instrument_type}&region={region}&delay={delay}"
            f"&universe={universe}&limit={limit}&offset={offset}"
        )
        if dataset_id:
            path += f"&dataset.id={dataset_id}"
        if search:
            path += f"&search={search}"
        result = client.get_json(path)
        batch = result.get("results", [])
        fields.extend(batch)
        if len(batch) < limit:
            break
        offset += limit
    return fields[:max_records]


def select_seed_fields(fields: list[dict[str, Any]], max_fields: int = 40) -> list[dict[str, Any]]:
    """Input: data-field records. Output: ranked seed fields. Prefer high coverage and non-grouping fields."""
    usable = []
    for field in fields:
        field_id = field.get("id")
        if not field_id:
            continue
        if field_id in {"country", "industry", "subindustry", "currency", "market", "sector", "exchange"}:
            continue
        usable.append(field)

    def score(field: dict[str, Any]) -> tuple[float, float, str]:
        coverage = field.get("coverage") or 0
        alpha_count = field.get("alphaCount") or 0
        return (float(coverage), float(alpha_count), str(field.get("id")))

    return sorted(usable, key=score, reverse=True)[:max_fields]


def field_ids(fields: list[dict[str, Any]]) -> set[str]:
    """Input: data-field records. Output: set of field ids. Support expression complexity checks."""
    return {str(field["id"]) for field in fields if field.get("id")}
```

- [ ] **Step 3: Run syntax check**

Run:

```bash
python -m py_compile wqb/knowledge.py wqb/data_catalog.py
```

Expected: no output and exit code 0.

- [ ] **Step 4: Optional checkpoint**

If git becomes valid:

```bash
git add wqb/knowledge.py wqb/data_catalog.py
git commit -m "feat: add knowledge and data catalog clients"
```

Expected now: skip commit.

## Task 7: Generator and Simulation Payloads

**Files:**
- Create: `wqb/generator.py`
- Create: `tests/test_generator.py`
- Test: `python -m unittest tests.test_generator -v`

- [ ] **Step 1: Write generator tests**

Create `tests/test_generator.py`:

```python
import unittest

from wqb.generator import build_settings, generate_seed_candidates, simulation_payload


class GeneratorTests(unittest.TestCase):
    def test_build_settings_uses_stage1_config(self):
        settings = build_settings(
            {
                "instrument_type": "EQUITY",
                "region": "USA",
                "universe": "TOP3000",
                "delay": 1,
                "decay": 4,
                "neutralization": "SUBINDUSTRY",
                "truncation": 0.08,
                "pasteurization": "ON",
                "unit_handling": "VERIFY",
                "nan_handling": "OFF",
                "language": "FASTEXPR",
            }
        )

        self.assertEqual(settings["region"], "USA")
        self.assertEqual(settings["language"], "FASTEXPR")
        self.assertFalse(settings["visualization"])

    def test_simulation_payload_shape(self):
        payload = simulation_payload({"region": "USA"}, "rank(close)")

        self.assertEqual(payload["type"], "REGULAR")
        self.assertEqual(payload["settings"], {"region": "USA"})
        self.assertEqual(payload["regular"], "rank(close)")

    def test_generate_seed_candidates_limits_count(self):
        fields = [{"id": "news_score"}, {"id": "volume"}]
        candidates = generate_seed_candidates(fields, {"region": "USA"}, max_count=3, generation=0)

        self.assertLessEqual(len(candidates), 3)
        self.assertTrue(all(candidate.expression for candidate in candidates))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run failing generator tests**

Run:

```bash
python -m unittest tests.test_generator -v
```

Expected: fail because `wqb.generator` does not exist.

- [ ] **Step 3: Implement generator**

Create `wqb/generator.py`:

```python
from typing import Any

from wqb.models import AlphaCandidate


LOOKBACKS = [5, 10, 20, 60, 120]
BASE_TEMPLATES = [
    "rank({field})",
    "-rank({field})",
    "rank(ts_mean({field}, {window}))",
    "-rank(ts_mean({field}, {window}))",
    "rank(ts_delta({field}, {window}))",
    "-rank(ts_delta({field}, {window}))",
    "group_neutralize(rank({field}), subindustry)",
]


def build_settings(config: dict[str, Any]) -> dict[str, Any]:
    """Input: run config. Output: WQB simulation settings dict. Convert config names to platform names."""
    return {
        "instrumentType": config["instrument_type"],
        "region": config["region"],
        "universe": config["universe"],
        "delay": config["delay"],
        "decay": config["decay"],
        "neutralization": config["neutralization"],
        "truncation": config["truncation"],
        "pasteurization": config["pasteurization"],
        "unitHandling": config["unit_handling"],
        "nanHandling": config["nan_handling"],
        "language": config["language"],
        "visualization": False,
    }


def simulation_payload(settings: dict[str, Any], expression: str) -> dict[str, Any]:
    """Input: settings and expression. Output: WQB regular simulation payload."""
    return {"type": "REGULAR", "settings": settings, "regular": expression}


def generate_seed_candidates(
    fields: list[dict[str, Any]],
    settings: dict[str, Any],
    max_count: int,
    generation: int,
) -> list[AlphaCandidate]:
    """Input: fields, settings, count, generation. Output: seed Alpha candidates from simple templates."""
    candidates: list[AlphaCandidate] = []
    for field in fields:
        field_id = field.get("id")
        if not field_id:
            continue
        for template in BASE_TEMPLATES:
            windows = LOOKBACKS if "{window}" in template else [None]
            for window in windows:
                expression = template.format(field=field_id, window=window)
                candidates.append(
                    AlphaCandidate(
                        expression=expression,
                        settings=settings,
                        generation=generation,
                        tags=["seed"],
                    )
                )
                if len(candidates) >= max_count:
                    return candidates
    return candidates
```

- [ ] **Step 4: Run generator tests**

Run:

```bash
python -m unittest tests.test_generator -v
```

Expected: pass.

- [ ] **Step 5: Optional checkpoint**

If git becomes valid:

```bash
git add wqb/generator.py tests/test_generator.py
git commit -m "feat: generate stage1 simulation payloads"
```

Expected now: skip commit.

## Task 8: Simulator

**Files:**
- Create: `wqb/simulator.py`
- No live call until Task 11 smoke test.

- [ ] **Step 1: Implement simulator module**

Create `wqb/simulator.py`:

```python
import time
from typing import Any


def submit_simulation(client, payload: dict[str, Any]) -> str:
    """Input: WQB client and simulation payload. Output: progress URL. Submit one simulation."""
    response = client.post_json("/simulations", payload)
    location = response.headers.get("Location")
    if not location:
        raise RuntimeError("simulation response missing Location header")
    return location


def poll_simulation(client, progress_url: str) -> dict[str, Any]:
    """Input: WQB client and progress URL. Output: final progress JSON. Poll until platform says complete."""
    while True:
        response = client.request("GET", progress_url)
        retry_after = response.headers.get("Retry-After")
        if retry_after:
            time.sleep(float(retry_after))
            continue
        response.raise_for_status()
        return response.json()


def extract_alpha_id(progress: dict[str, Any]) -> str:
    """Input: simulation progress JSON. Output: alpha id. Normalize platform result variants."""
    alpha_id = progress.get("alpha")
    if isinstance(alpha_id, str) and alpha_id:
        return alpha_id
    if isinstance(alpha_id, dict) and alpha_id.get("id"):
        return str(alpha_id["id"])
    raise RuntimeError(f"simulation progress missing alpha id: {progress}")
```

- [ ] **Step 2: Run syntax check**

Run:

```bash
python -m py_compile wqb/simulator.py
```

Expected: no output and exit code 0.

- [ ] **Step 3: Optional checkpoint**

If git becomes valid:

```bash
git add wqb/simulator.py
git commit -m "feat: add simulation polling"
```

Expected now: skip commit.

## Task 9: Optimizer Rules

**Files:**
- Create: `wqb/optimizer.py`
- Create: `tests/test_optimizer.py`
- Test: `python -m unittest tests.test_optimizer -v`

- [ ] **Step 1: Write optimizer tests**

Create `tests/test_optimizer.py`:

```python
import unittest

from wqb.models import CheckItem, CheckSummary
from wqb.optimizer import actions_for_check_summary


class OptimizerTests(unittest.TestCase):
    def test_low_sharpe_maps_to_signal_actions(self):
        summary = CheckSummary(
            alpha_id="a1",
            hard_pass=False,
            failed=[CheckItem(name="LOW_SHARPE", result="FAIL")],
            warnings=[],
            pending=[],
            metrics={"sharpe": 0.8},
        )

        actions = actions_for_check_summary("parent", summary)

        self.assertIn("flip_direction", {action.action_type for action in actions})
        self.assertIn("change_window", {action.action_type for action in actions})

    def test_high_turnover_maps_to_smoothing(self):
        summary = CheckSummary(
            alpha_id="a1",
            hard_pass=False,
            failed=[CheckItem(name="HIGH_TURNOVER", result="FAIL")],
            warnings=[],
            pending=[],
            metrics={"turnover": 0.9},
        )

        actions = actions_for_check_summary("parent", summary)

        self.assertIn("increase_decay", {action.action_type for action in actions})
        self.assertIn("smooth_signal", {action.action_type for action in actions})


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run failing optimizer tests**

Run:

```bash
python -m unittest tests.test_optimizer -v
```

Expected: fail because `wqb.optimizer` does not exist.

- [ ] **Step 3: Implement optimizer rules**

Create `wqb/optimizer.py`:

```python
from wqb.models import CheckSummary, OptimizationAction


FAILURE_ACTIONS = {
    "LOW_SHARPE": ["flip_direction", "change_window", "change_neutralization", "rank_or_zscore"],
    "LOW_2Y_SHARPE": ["change_window", "change_field", "change_neutralization"],
    "LOW_FITNESS": ["improve_returns", "reduce_turnover", "change_window"],
    "LOW_RETURNS": ["flip_direction", "change_field", "rank_or_zscore"],
    "HIGH_TURNOVER": ["increase_decay", "smooth_signal", "add_trade_when"],
    "LOW_TURNOVER": ["decrease_decay", "shorten_window"],
    "CONCENTRATED_WEIGHT": ["rank_or_scale", "adjust_truncation", "add_backfill"],
    "LOW_SUB_UNIVERSE_SHARPE": ["change_field", "change_neutralization", "reduce_overfit"],
    "LOW_ROBUST_UNIVERSE_SHARPE.WITH_RATIO": ["change_field", "change_neutralization", "reduce_overfit"],
    "LOW_ROBUST_UNIVERSE_RETURNS": ["change_field", "flip_direction", "reduce_overfit"],
    "SELF_CORRELATION": ["change_dataset", "change_operator_family", "new_hypothesis"],
    "PROD_CORRELATION": ["change_dataset", "change_operator_family", "new_hypothesis"],
    "DATA_DIVERSITY": ["change_dataset", "use_theme_field"],
    "MATCHES_THEMES": ["use_theme_field", "refresh_power_pool_catalog"],
    "MATCHES_COMPETITION": ["refresh_competition_rules", "use_theme_field"],
}


def actions_for_check_summary(parent_hash: str, summary: CheckSummary) -> list[OptimizationAction]:
    """Input: parent expression hash and check summary. Output: ordered optimization actions."""
    actions: list[OptimizationAction] = []
    for failed in summary.failed + summary.pending:
        for action_type in FAILURE_ACTIONS.get(failed.name, ["change_field"]):
            actions.append(
                OptimizationAction(
                    parent_hash=parent_hash,
                    reason=failed.name,
                    action_type=action_type,
                    details={"alpha_id": summary.alpha_id, "result": failed.result},
                )
            )
    return actions
```

- [ ] **Step 4: Run optimizer tests**

Run:

```bash
python -m unittest tests.test_optimizer -v
```

Expected: pass.

- [ ] **Step 5: Optional checkpoint**

If git becomes valid:

```bash
git add wqb/optimizer.py tests/test_optimizer.py
git commit -m "feat: map failed checks to optimization actions"
```

Expected now: skip commit.

## Task 10: CLI Orchestration

**Files:**
- Create: `wqb/cli.py`
- Modify: `wqb/generator.py` if a helper is needed for payload serialization.
- Test with `dry-run` before any live simulation.

- [ ] **Step 1: Implement CLI**

Create `wqb/cli.py`:

```python
import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from wqb.checker import fetch_check_summary
from wqb.client import WQBClient
from wqb.config import load_config
from wqb.data_catalog import fetch_data_fields, field_ids, select_seed_fields
from wqb.expression import expression_hash, is_power_pool_complexity_ok
from wqb.generator import build_settings, generate_seed_candidates, simulation_payload
from wqb.knowledge import fetch_knowledge_snapshot
from wqb.optimizer import actions_for_check_summary
from wqb.recorder import RunRecorder
from wqb.simulator import extract_alpha_id, poll_simulation, submit_simulation


def make_run_dir(config: dict[str, Any]) -> Path:
    """Input: run config. Output: run directory path. Create a timestamped run location."""
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    return Path(config["run_root"]) / run_id


def build_client(config: dict[str, Any]) -> WQBClient:
    """Input: run config. Output: WQB client. Centralize client construction."""
    return WQBClient(
        timeout_seconds=int(config["request_timeout_seconds"]),
        max_retries=int(config["max_retries"]),
        base_backoff_seconds=int(config["base_backoff_seconds"]),
    )


def dry_run(config: dict[str, Any]) -> None:
    """Input: run config. Output: terminal summary. Generate payloads without hitting simulation endpoints."""
    settings = build_settings(config)
    sample_fields = [{"id": "close"}, {"id": "volume"}, {"id": "returns"}]
    candidates = generate_seed_candidates(sample_fields, settings, int(config["max_alphas_per_round"]), generation=0)
    known_fields = field_ids(sample_fields)
    payloads = []
    for candidate in candidates:
        complexity = is_power_pool_complexity_ok(
            candidate.expression,
            known_fields,
            int(config["power_pool_operator_limit"]),
            int(config["power_pool_field_limit"]),
        )
        payloads.append(
            {
                "expression_hash": expression_hash(candidate.expression),
                "expression": candidate.expression,
                "complexity_ok": complexity.ok,
                "payload": simulation_payload(candidate.settings, candidate.expression),
            }
        )
    print(json.dumps({"payload_count": len(payloads), "payloads": payloads[:5]}, ensure_ascii=False, indent=2))


def smoke(config: dict[str, Any]) -> None:
    """Input: run config. Output: run artifacts. Execute a tiny live simulation/check cycle."""
    run_dir = make_run_dir(config)
    recorder = RunRecorder(run_dir)
    client = build_client(config)
    client.authenticate()
    snapshot = fetch_knowledge_snapshot(client, list(config.get("knowledge_queries", []))[:3])
    recorder.write_markdown("run_summary.md", "# Smoke Test\n\nKnowledge snapshot fetched.\n")
    (run_dir / "knowledge_snapshot.json").write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")

    fields = fetch_data_fields(
        client,
        config["instrument_type"],
        config["region"],
        int(config["delay"]),
        config["universe"],
        max_records=20,
    )
    seed_fields = select_seed_fields(fields, max_fields=5)
    settings = build_settings(config)
    max_count = min(int(config["max_alphas_per_round"]), 3)
    candidates = generate_seed_candidates(seed_fields, settings, max_count, generation=0)
    for candidate in candidates:
        expr_hash = expression_hash(candidate.expression)
        payload = simulation_payload(candidate.settings, candidate.expression)
        progress_url = submit_simulation(client, payload)
        progress = poll_simulation(client, progress_url)
        alpha_id = extract_alpha_id(progress)
        summary = fetch_check_summary(client, alpha_id)
        recorder.append_jsonl(
            "all_alphas.jsonl",
            {
                "alpha_id": alpha_id,
                "expression_hash": expr_hash,
                "status": "CHECKED",
                "hard_pass": summary.hard_pass,
                "failed": [item.name for item in summary.failed],
                "pending": [item.name for item in summary.pending],
                "warnings": [item.name for item in summary.warnings],
            },
        )
        print(f"checked alpha_id={alpha_id} hard_pass={summary.hard_pass}")
        break


def run_stage1(config: dict[str, Any]) -> None:
    """Input: run config. Output: run artifacts. Run Stage 1 search and optimization workflow."""
    run_dir = make_run_dir(config)
    recorder = RunRecorder(run_dir)
    client = build_client(config)
    client.authenticate()
    snapshot = fetch_knowledge_snapshot(client, list(config.get("knowledge_queries", [])))
    (run_dir / "knowledge_snapshot.json").write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")

    fields = fetch_data_fields(
        client,
        config["instrument_type"],
        config["region"],
        int(config["delay"]),
        config["universe"],
        max_records=300,
    )
    seed_fields = select_seed_fields(fields, max_fields=40)
    settings = build_settings(config)
    candidates_rows: list[dict[str, Any]] = []
    seen = recorder.seen_expression_hashes()

    for generation in range(int(config["max_rounds"])):
        candidates = generate_seed_candidates(
            seed_fields,
            settings,
            int(config["max_alphas_per_round"]),
            generation=generation,
        )
        for candidate in candidates:
            expr_hash = expression_hash(candidate.expression)
            if expr_hash in seen:
                continue
            seen.add(expr_hash)
            payload = simulation_payload(candidate.settings, candidate.expression)
            progress_url = submit_simulation(client, payload)
            progress = poll_simulation(client, progress_url)
            alpha_id = extract_alpha_id(progress)
            summary = fetch_check_summary(client, alpha_id)
            record = {
                "alpha_id": alpha_id,
                "expression_hash": expr_hash,
                "generation": generation,
                "status": "CHECKED",
                "hard_pass": summary.hard_pass,
                "metrics": summary.metrics,
                "failed": [item.name for item in summary.failed],
                "pending": [item.name for item in summary.pending],
                "warnings": [item.name for item in summary.warnings],
                "expression": candidate.expression,
            }
            recorder.append_jsonl("all_alphas.jsonl", record)
            if summary.hard_pass:
                row = {
                    "alpha_id": alpha_id,
                    "expression_hash": expr_hash,
                    "sharpe": summary.metrics.get("sharpe"),
                    "fitness": summary.metrics.get("fitness"),
                    "turnover": summary.metrics.get("turnover"),
                    "returns": summary.metrics.get("returns"),
                    "warnings": ",".join(item.name for item in summary.warnings),
                }
                candidates_rows.append(row)
                recorder.write_candidates(candidates_rows)
                if config["stop_after_first_candidate"]:
                    recorder.write_markdown("run_summary.md", f"# Stage 1 Summary\n\nCandidate found: `{alpha_id}`\n")
                    print(f"candidate found alpha_id={alpha_id}")
                    return
            for action in actions_for_check_summary(expr_hash, summary):
                recorder.append_jsonl(
                    "optimization_trace.jsonl",
                    {
                        "parent_hash": action.parent_hash,
                        "reason": action.reason,
                        "action_type": action.action_type,
                        "details": action.details,
                    },
                )

    recorder.write_candidates(candidates_rows)
    recorder.write_markdown("run_summary.md", "# Stage 1 Summary\n\nNo hard-check-passing candidate found within budget.\n")
    print(f"stage1 complete run_dir={run_dir}")


def parse_args() -> argparse.Namespace:
    """Input: command line. Output: parsed args. Define Stage 1 CLI commands."""
    parser = argparse.ArgumentParser(description="WorldQuant Brain Stage 1 workflow")
    parser.add_argument("command", choices=["dry-run", "smoke", "run-stage1"])
    parser.add_argument("--config", default="configs/stage1_usa_d1.yaml")
    parser.add_argument("--max-alphas-per-round", type=int, default=None)
    parser.add_argument("--max-rounds", type=int, default=None)
    return parser.parse_args()


def main() -> None:
    """Input: CLI args. Output: command side effects. Dispatch Stage 1 commands."""
    args = parse_args()
    overrides = {
        "max_alphas_per_round": args.max_alphas_per_round,
        "max_rounds": args.max_rounds,
    }
    config = load_config(args.config, overrides=overrides)
    if args.command == "dry-run":
        dry_run(config)
    elif args.command == "smoke":
        smoke(config)
    elif args.command == "run-stage1":
        run_stage1(config)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run syntax check**

Run:

```bash
python -m py_compile wqb/cli.py
```

Expected: no output and exit code 0.

- [ ] **Step 3: Run dry-run**

Run:

```bash
python -m wqb.cli dry-run --config configs/stage1_usa_d1.yaml --max-alphas-per-round 5
```

Expected: JSON output with `"payload_count": 5` and no network simulation request.

- [ ] **Step 4: Optional checkpoint**

If git becomes valid:

```bash
git add wqb/cli.py
git commit -m "feat: add stage1 CLI orchestration"
```

Expected now: skip commit.

## Task 11: Launchers

**Files:**
- Create: `run_stage1.sh`
- Create: `run_stage1.ps1`

- [ ] **Step 1: Create Bash launcher**

Create `run_stage1.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail

MAX_ALPHAS_PER_ROUND=50
MAX_ROUNDS=5
CONFIG_PATH="configs/stage1_usa_d1.yaml"

python -m wqb.cli run-stage1 \
  --config "${CONFIG_PATH}" \
  --max-alphas-per-round "${MAX_ALPHAS_PER_ROUND}" \
  --max-rounds "${MAX_ROUNDS}"
```

- [ ] **Step 2: Create PowerShell launcher**

Create `run_stage1.ps1`:

```powershell
$ErrorActionPreference = "Stop"

$MaxAlphasPerRound = 50
$MaxRounds = 5
$ConfigPath = "configs/stage1_usa_d1.yaml"

python -m wqb.cli run-stage1 `
  --config $ConfigPath `
  --max-alphas-per-round $MaxAlphasPerRound `
  --max-rounds $MaxRounds
```

- [ ] **Step 3: Run launcher syntax checks**

Run:

```bash
python -m wqb.cli dry-run --config configs/stage1_usa_d1.yaml --max-alphas-per-round 3
```

Expected: dry-run JSON with 3 payloads.

- [ ] **Step 4: Optional checkpoint**

If git becomes valid:

```bash
git add run_stage1.sh run_stage1.ps1
git commit -m "chore: add stage1 launchers"
```

Expected now: skip commit.

## Task 12: Local Test Sweep

**Files:**
- Modify only files required to fix failing tests from previous tasks.

- [ ] **Step 1: Run all unit tests**

Run:

```bash
python -m unittest discover -s tests -v
```

Expected: all tests pass.

- [ ] **Step 2: Run compile sweep**

Run:

```bash
python -m compileall wqb tests
```

Expected: compile succeeds.

- [ ] **Step 3: Run dry-run**

Run:

```bash
python -m wqb.cli dry-run --config configs/stage1_usa_d1.yaml --max-alphas-per-round 5
```

Expected: 5 generated payloads and no live simulation.

- [ ] **Step 4: Update `todo.md`**

Append:

```markdown
- 2026-06-28：Stage 1 本地单元测试、编译检查和 dry-run 已通过；下一步进行 live smoke test。
```

- [ ] **Step 5: Optional checkpoint**

If git becomes valid:

```bash
git add wqb tests configs run_stage1.sh run_stage1.ps1 todo.md
git commit -m "test: verify stage1 local workflow"
```

Expected now: skip commit.

## Task 13: Live Smoke Test

**Files:**
- Modify implementation files only if smoke test reveals an API-shape mismatch.
- Modify: `todo.md`

- [ ] **Step 1: Confirm environment variables exist without printing values**

Run:

```powershell
if ($env:WQB_USERNAME) { "WQB_USERNAME set" } else { "WQB_USERNAME missing" }
if ($env:WQB_PASSWORD) { "WQB_PASSWORD set" } else { "WQB_PASSWORD missing" }
```

Expected:

```text
WQB_USERNAME set
WQB_PASSWORD set
```

- [ ] **Step 2: Run smoke command**

Run:

```bash
python -m wqb.cli smoke --config configs/stage1_usa_d1.yaml --max-alphas-per-round 3 --max-rounds 1
```

Expected:

- The client authenticates.
- `runs/<run_id>/knowledge_snapshot.json` is created.
- One simulation is submitted.
- One alpha id is fetched.
- `/alphas/{id}/check` is classified.
- `runs/<run_id>/all_alphas.jsonl` has one checked record.

- [ ] **Step 3: Inspect smoke artifacts**

Run:

```powershell
Get-ChildItem -Directory .\runs | Sort-Object LastWriteTime -Descending | Select-Object -First 1
```

Then inspect the latest `all_alphas.jsonl`:

```powershell
Get-ChildItem -Directory .\runs | Sort-Object LastWriteTime -Descending | Select-Object -First 1 | ForEach-Object { Get-Content -Raw -LiteralPath (Join-Path $_.FullName 'all_alphas.jsonl') }
```

Expected: one JSONL record with `alpha_id`, `expression_hash`, `hard_pass`, and check lists. No credentials appear.

- [ ] **Step 4: Fix only API-shape mismatches**

If the smoke test fails because the platform response shape differs, make the smallest change in the relevant module:

- Simulation submit/poll mismatch: `wqb/simulator.py`.
- Check response mismatch: `wqb/checker.py`.
- Data-field mismatch: `wqb/data_catalog.py`.
- Client retry/auth mismatch: `wqb/client.py`.

Run after the fix:

```bash
python -m unittest discover -s tests -v
python -m wqb.cli smoke --config configs/stage1_usa_d1.yaml --max-alphas-per-round 3 --max-rounds 1
```

Expected: tests pass and smoke test completes.

- [ ] **Step 5: Update `todo.md`**

Append one of:

```markdown
- 2026-06-28：Live smoke test 已完成，登录、simulation、poll、check、记录链路跑通。
```

or:

```markdown
- 2026-06-28：Live smoke test 未通过，失败点为 `<具体模块/接口>`，已记录为下一步修复项。
```

- [ ] **Step 6: Optional checkpoint**

If git becomes valid:

```bash
git add wqb tests runs todo.md
git commit -m "test: complete stage1 live smoke"
```

Expected now: skip commit.

## Task 14: Full Stage 1 Run

**Files:**
- Modify implementation files only for defects found during the run.
- Modify: `todo.md`

- [ ] **Step 1: Start full run**

Run from PowerShell:

```powershell
.\run_stage1.ps1
```

Expected:

- The run creates a new `runs/<run_id>/`.
- The workflow uses up to 50 Alphas per round and up to 5 rounds.
- A candidate stops the run if `stop_after_first_candidate` is true.

- [ ] **Step 2: Monitor rate limiting and errors**

If HTTP 429 appears, do not increase concurrency. Confirm the client waits and retries. If repeated 429 persists, stop the run and set smaller launch parameters:

```powershell
$MaxAlphasPerRound = 10
$MaxRounds = 3
```

Expected: slower but stable execution.

- [ ] **Step 3: Review candidates**

Inspect:

```powershell
Get-ChildItem -Directory .\runs | Sort-Object LastWriteTime -Descending | Select-Object -First 1 | ForEach-Object { Get-Content -Raw -LiteralPath (Join-Path $_.FullName 'candidates.csv') }
```

Expected:

- If candidates exist, each row has hard-check-passing `alpha_id`.
- If no candidate exists, `run_summary.md` explains failure patterns.

- [ ] **Step 4: Report user-facing outcome**

Prepare a concise summary containing:

- Latest run directory.
- Candidate count.
- Candidate alpha ids if any.
- Failed check distribution if no candidate.
- Whether Power Pool was attempted.
- No credentials or session material.

- [ ] **Step 5: Update `todo.md`**

Append:

```markdown
- 2026-06-28：Full Stage 1 run 已完成，候选数量：`<数量>`；结果目录：`runs/<run_id>`；遗留问题：`<无或具体问题>`。
```

- [ ] **Step 6: Optional checkpoint**

If git becomes valid:

```bash
git add wqb tests configs run_stage1.sh run_stage1.ps1 todo.md
git commit -m "feat: run stage1 WorldQuant workflow"
```

Expected now: skip commit.

## Self-Review

Spec coverage:

- CLI workflow: Tasks 10, 11, 14.
- Environment-variable credentials: Task 3.
- API client with retry and `Retry-After`: Task 3.
- Knowledge snapshot: Task 6.
- Data-field pool: Task 6.
- Expression generation and Power Pool complexity limits: Tasks 2 and 7.
- Simulation and polling: Task 8.
- `/alphas/{id}/check` classification: Task 5.
- Optimization loop actions: Task 9 and Task 10.
- JSONL/CSV/Markdown artifacts and resume: Task 4.
- Dry-run, local tests, smoke, full run: Tasks 10, 12, 13, 14.
- No auto submit: Task 10 implements no submit endpoint and Task 14 only reports candidates.

Placeholder scan:

- No unresolved placeholder markers or undefined implementation placeholders remain.
- Open API unknowns are handled as live-smoke mismatch fixes in Task 13.

Type consistency:

- `AlphaCandidate`, `CheckSummary`, `CheckItem`, and `OptimizationAction` are defined in Task 2 and used consistently in later tasks.
- `WQBClient` methods are defined in Task 3 and used consistently in Tasks 6, 8, 10, 13, and 14.
- Test commands use `unittest` consistently because `pytest` is unavailable.
