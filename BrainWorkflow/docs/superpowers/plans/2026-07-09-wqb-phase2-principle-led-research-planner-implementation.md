# WQB Phase 2 Principle-Led Research Planner Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a read-only research planner that refreshes current WorldQuant BRAIN incentives and produces 3-5 user-selectable research option cards before any concrete alpha batch plan is created.

**Architecture:** Add focused modules for principle contracts, official rule refresh, opportunity scoring, and decision logging. Expose the workflow through a CLI command that fetches current evidence, scores opportunities, writes durable option cards, and stops for user choice.

**Tech Stack:** Python standard library, existing `requests`-based `WQBClient`, `unittest`, existing `RunRecorder` patterns, Markdown/JSONL knowledge artifacts.

## Global Constraints

- Do not hardcode API credentials; use `WQB_USERNAME` and `WQB_PASSWORD`.
- Do not submit simulations or alphas from the research planner.
- Refresh dynamic platform sources before generating options when API access is available.
- If refresh fails, use cached evidence only with visible staleness and uncertainty.
- Generate option cards before creating concrete alpha batches.
- Ask the user to choose an option before planning activity, region, delay, data, templates, or batch execution.
- Only alphas passing all required platform checks may enter submit-candidate lists; this planner does not promote alphas.
- Put new hyperparameters immediately below imports in each code file.
- Add a short input/output/function-purpose comment at the entry of each new function written for this project.

---

## File Structure

- Create `wqb/principle_model.py`
  - Owns dataclasses and validation for evidence, incentive snapshots, score breakdowns, and option cards.
- Create `wqb/rule_refresh.py`
  - Fetches official platform sources through `WQBClient` and normalizes them into `IncentiveSnapshot`.
- Create `wqb/research_planner.py`
  - Scores active opportunities against the principle stack and emits option cards.
- Create `wqb/decision_log.py`
  - Writes option cards and user decisions into JSONL and Markdown knowledge files.
- Modify `wqb/cli.py`
  - Adds `plan-research-options`, a read-only command that refreshes rules and prints option cards.
- Create tests:
  - `tests/test_principle_model.py`
  - `tests/test_rule_refresh.py`
  - `tests/test_research_planner.py`
  - `tests/test_decision_log.py`
  - Extend `tests/test_cli.py`
- Update docs:
  - `knowledge/wiki/00_principles/principle_stack.md`
  - `knowledge/wiki/70_decisions/README.md`
  - `docs/knowledge/wqb_rules.md`

---

### Task 1: Principle Model Contracts

**Files:**
- Create: `wqb/principle_model.py`
- Test: `tests/test_principle_model.py`

**Interfaces:**
- Produces:
  - `SourceEvidence(source_type: str, path: str, title: str, timestamp: str, stale: bool = False, note: str = "")`
  - `IncentiveSnapshot(generated_at: str, account: dict[str, Any], activities: list[dict[str, Any]], competitions: list[dict[str, Any]], power_pool_boards: list[dict[str, str]], rule_pages: dict[str, str], evidence: list[SourceEvidence], refresh_errors: list[dict[str, str]])`
  - `ScoreBreakdown(total: float, components: dict[str, float], penalties: dict[str, float], reasons: list[str])`
  - `OptionCard(title: str, primary_incentive: str, secondary_incentives: list[str], why_now: str, candidate_scope: str, expected_asset_value: str, correlation_risk: str, resource_cost: str, evidence: list[SourceEvidence], failure_modes: list[str], decision_needed: str, score: ScoreBreakdown)`
  - `option_card_to_dict(card: OptionCard) -> dict[str, Any]`
  - `validate_option_card(card: OptionCard) -> None`

- Consumes: Python standard library only.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_principle_model.py`:

```python
import unittest

from wqb.principle_model import (
    OptionCard,
    ScoreBreakdown,
    SourceEvidence,
    option_card_to_dict,
    validate_option_card,
)


class PrincipleModelTest(unittest.TestCase):
    def test_option_card_to_dict_serializes_nested_evidence(self):
        evidence = SourceEvidence(
            source_type="api",
            path="/competitions/PAC2026",
            title="Python Alphas Competition 2026",
            timestamp="2026-07-09T00:00:00Z",
        )
        card = OptionCard(
            title="PAC feasibility check",
            primary_incentive="competition",
            secondary_incentives=["learning"],
            why_now="Active competition window is visible.",
            candidate_scope="Python alpha feasibility only.",
            expected_asset_value="May unlock reusable Python alpha workflow.",
            correlation_risk="Unknown until alpha expressions exist.",
            resource_cost="Read-only API refresh plus no simulations.",
            evidence=[evidence],
            failure_modes=["Competition submission may be disabled."],
            decision_needed="Choose whether to spend a feasibility slot.",
            score=ScoreBreakdown(
                total=6.0,
                components={"competition_expected_value": 4.0, "learning": 2.0},
                penalties={"tooling_gap_cost": 0.0},
                reasons=["Active competition evidence exists."],
            ),
        )

        row = option_card_to_dict(card)

        self.assertEqual(row["title"], "PAC feasibility check")
        self.assertEqual(row["evidence"][0]["path"], "/competitions/PAC2026")
        self.assertEqual(row["score"]["total"], 6.0)

    def test_validate_option_card_rejects_missing_required_text(self):
        card = OptionCard(
            title="",
            primary_incentive="power_pool",
            secondary_incentives=[],
            why_now="Board exists.",
            candidate_scope="USA D1.",
            expected_asset_value="Simple alpha asset.",
            correlation_risk="Medium.",
            resource_cost="One read-only refresh.",
            evidence=[],
            failure_modes=[],
            decision_needed="Choose this option.",
            score=ScoreBreakdown(total=1.0, components={}, penalties={}, reasons=[]),
        )

        with self.assertRaises(ValueError):
            validate_option_card(card)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests to verify failure**

Run:

```powershell
python -m unittest tests.test_principle_model -v
```

Expected: fail with `ModuleNotFoundError: No module named 'wqb.principle_model'`.

- [ ] **Step 3: Implement `wqb/principle_model.py`**

Create `wqb/principle_model.py`:

```python
from dataclasses import asdict, dataclass
from typing import Any


REQUIRED_OPTION_TEXT_FIELDS = [
    "title",
    "primary_incentive",
    "why_now",
    "candidate_scope",
    "expected_asset_value",
    "correlation_risk",
    "resource_cost",
    "decision_needed",
]


@dataclass(frozen=True)
class SourceEvidence:
    source_type: str
    path: str
    title: str
    timestamp: str
    stale: bool = False
    note: str = ""


@dataclass(frozen=True)
class IncentiveSnapshot:
    generated_at: str
    account: dict[str, Any]
    activities: list[dict[str, Any]]
    competitions: list[dict[str, Any]]
    power_pool_boards: list[dict[str, str]]
    rule_pages: dict[str, str]
    evidence: list[SourceEvidence]
    refresh_errors: list[dict[str, str]]


@dataclass(frozen=True)
class ScoreBreakdown:
    total: float
    components: dict[str, float]
    penalties: dict[str, float]
    reasons: list[str]


@dataclass(frozen=True)
class OptionCard:
    title: str
    primary_incentive: str
    secondary_incentives: list[str]
    why_now: str
    candidate_scope: str
    expected_asset_value: str
    correlation_risk: str
    resource_cost: str
    evidence: list[SourceEvidence]
    failure_modes: list[str]
    decision_needed: str
    score: ScoreBreakdown


def option_card_to_dict(card: OptionCard) -> dict[str, Any]:
    """Input: OptionCard. Output: dict[str, Any]. Convert a research option to JSON-safe data."""
    return asdict(card)


def validate_option_card(card: OptionCard) -> None:
    """Input: OptionCard. Output: None. Raise ValueError when required user-facing fields are empty."""
    row = option_card_to_dict(card)
    missing = [field for field in REQUIRED_OPTION_TEXT_FIELDS if not str(row.get(field, "")).strip()]
    if missing:
        raise ValueError(f"option card missing required fields: {', '.join(missing)}")
    if not card.evidence:
        raise ValueError("option card must include at least one evidence source")
    if not card.score.reasons:
        raise ValueError("option card score must include reasons")
```

- [ ] **Step 4: Run the tests to verify pass**

Run:

```powershell
python -m unittest tests.test_principle_model -v
```

Expected: 2 tests pass.

- [ ] **Step 5: Commit**

Run:

```powershell
git add BrainWorkflow/wqb/principle_model.py BrainWorkflow/tests/test_principle_model.py
git commit -m "add principle model contracts"
```

Expected: commit succeeds.

---

### Task 2: Official Rule Refresh

**Files:**
- Create: `wqb/rule_refresh.py`
- Test: `tests/test_rule_refresh.py`

**Interfaces:**
- Consumes:
  - `WQBClient.get_json(path: str) -> Any`
  - `WQBClient.options_json(path: str) -> Any`
  - `IncentiveSnapshot`
  - `SourceEvidence`
- Produces:
  - `DEFAULT_RULE_PAGE_IDS: list[str]`
  - `refresh_incentive_snapshot(client: Any, generated_at: str) -> IncentiveSnapshot`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_rule_refresh.py`:

```python
import unittest

from wqb.rule_refresh import refresh_incentive_snapshot


class FakeClient:
    def __init__(self):
        self.get_paths = []
        self.option_paths = []

    def get_json(self, path):
        self.get_paths.append(path)
        if path == "/users/self":
            return {"id": "TO50928", "geniusLevel": "GOLD", "onboarding": {"status": "CONSULTANT_APPROVED"}}
        if path == "/events?limit=50&offset=0":
            return {"results": [{"id": "E1", "title": "Opportunity Webinar", "description": "Brain Community Score"}]}
        if path == "/competitions?limit=50&offset=0":
            return {"results": [{"id": "PAC2026", "name": "Python Alphas Competition 2026", "status": "ACCEPTED"}]}
        if path.startswith("/tutorial-pages/"):
            return {"id": path.rsplit("/", 1)[-1], "title": "Rule Page", "content": [{"type": "TEXT", "value": "rules"}]}
        raise AssertionError(path)

    def options_json(self, path):
        self.option_paths.append(path)
        return {
            "actions": {
                "GET": {
                    "board": {
                        "choices": [
                            {"value": "lyvRddy", "label": "USA/D1 Power Pool July'26"},
                            {"value": "Jypw8X4", "label": "USA/D1 Fast Datasets Power Pool June`26"},
                        ]
                    }
                }
            }
        }


class RuleRefreshTest(unittest.TestCase):
    def test_refresh_incentive_snapshot_normalizes_core_sources(self):
        client = FakeClient()

        snapshot = refresh_incentive_snapshot(client, generated_at="2026-07-09T00:00:00Z")

        self.assertEqual(snapshot.account["geniusLevel"], "GOLD")
        self.assertEqual(snapshot.competitions[0]["id"], "PAC2026")
        self.assertEqual(snapshot.power_pool_boards[0]["label"], "USA/D1 Power Pool July'26")
        self.assertIn("/users/self", client.get_paths)
        self.assertIn("/consultant/boards/power-pool", client.option_paths)
        self.assertEqual(snapshot.refresh_errors, [])
        self.assertGreaterEqual(len(snapshot.evidence), 4)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests to verify failure**

Run:

```powershell
python -m unittest tests.test_rule_refresh -v
```

Expected: fail with `ModuleNotFoundError: No module named 'wqb.rule_refresh'`.

- [ ] **Step 3: Implement `wqb/rule_refresh.py`**

Create `wqb/rule_refresh.py`:

```python
from typing import Any

from wqb.principle_model import IncentiveSnapshot, SourceEvidence


DEFAULT_RULE_PAGE_IDS = [
    "brain-genius",
    "osmosis-allocation-guide-consultants",
    "multiplier-rules",
    "getting-started-power-pool-alphas",
    "consultant-submission-tests",
    "multi-alpha-simulation",
]


def _safe_get(client: Any, path: str, errors: list[dict[str, str]]) -> Any:
    """Input: API client, path, error list. Output: JSON-like data or None. Fetch one GET source safely."""
    try:
        return client.get_json(path)
    except Exception as err:
        errors.append({"path": path, "error": type(err).__name__, "message": str(err)})
        return None


def _safe_options(client: Any, path: str, errors: list[dict[str, str]]) -> Any:
    """Input: API client, path, error list. Output: JSON-like data or None. Fetch one OPTIONS source safely."""
    try:
        return client.options_json(path)
    except Exception as err:
        errors.append({"path": path, "error": type(err).__name__, "message": str(err)})
        return None


def _results(payload: Any) -> list[dict[str, Any]]:
    """Input: JSON-like payload. Output: list[dict]. Extract paginated results safely."""
    if isinstance(payload, dict) and isinstance(payload.get("results"), list):
        return [item for item in payload["results"] if isinstance(item, dict)]
    return []


def _power_pool_choices(payload: Any) -> list[dict[str, str]]:
    """Input: OPTIONS payload. Output: board choice rows. Extract visible Power Pool board choices."""
    board = (((payload or {}).get("actions") or {}).get("GET") or {}).get("board") or {}
    choices = board.get("choices") or []
    rows = []
    for choice in choices:
        if isinstance(choice, dict) and choice.get("value") and choice.get("label"):
            rows.append({"value": str(choice["value"]), "label": str(choice["label"])})
    return rows


def _page_text(page: Any) -> str:
    """Input: tutorial page payload. Output: compact text. Preserve enough rule text for scoring evidence."""
    if not isinstance(page, dict):
        return ""
    content = page.get("content")
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts = []
    for block in content:
        if not isinstance(block, dict):
            continue
        value = block.get("value")
        if isinstance(value, str):
            parts.append(value)
        elif isinstance(value, dict) and value.get("content"):
            parts.append(str(value["content"]))
    return " ".join(parts)


def refresh_incentive_snapshot(client: Any, generated_at: str) -> IncentiveSnapshot:
    """Input: WQB-like client and timestamp. Output: IncentiveSnapshot. Refresh official incentive sources."""
    errors: list[dict[str, str]] = []
    evidence: list[SourceEvidence] = []

    account = _safe_get(client, "/users/self", errors) or {}
    evidence.append(SourceEvidence("api", "/users/self", "User account state", generated_at))

    events_payload = _safe_get(client, "/events?limit=50&offset=0", errors)
    evidence.append(SourceEvidence("api", "/events?limit=50&offset=0", "Events", generated_at))

    competitions_payload = _safe_get(client, "/competitions?limit=50&offset=0", errors)
    evidence.append(SourceEvidence("api", "/competitions?limit=50&offset=0", "Competitions", generated_at))

    power_pool_payload = _safe_options(client, "/consultant/boards/power-pool", errors)
    evidence.append(SourceEvidence("api", "/consultant/boards/power-pool", "Power Pool boards", generated_at))

    rule_pages: dict[str, str] = {}
    for page_id in DEFAULT_RULE_PAGE_IDS:
        path = f"/tutorial-pages/{page_id}"
        page = _safe_get(client, path, errors)
        if page is not None:
            rule_pages[page_id] = _page_text(page)
            evidence.append(SourceEvidence("api", path, str(page.get("title", page_id)), generated_at))

    return IncentiveSnapshot(
        generated_at=generated_at,
        account=account if isinstance(account, dict) else {},
        activities=_results(events_payload),
        competitions=_results(competitions_payload),
        power_pool_boards=_power_pool_choices(power_pool_payload),
        rule_pages=rule_pages,
        evidence=evidence,
        refresh_errors=errors,
    )
```

- [ ] **Step 4: Run the tests to verify pass**

Run:

```powershell
python -m unittest tests.test_rule_refresh tests.test_principle_model -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

Run:

```powershell
git add BrainWorkflow/wqb/rule_refresh.py BrainWorkflow/tests/test_rule_refresh.py
git commit -m "add incentive rule refresh"
```

Expected: commit succeeds.

---

### Task 3: Opportunity Scoring And Option Cards

**Files:**
- Create: `wqb/research_planner.py`
- Test: `tests/test_research_planner.py`

**Interfaces:**
- Consumes:
  - `IncentiveSnapshot`
  - `OptionCard`
  - `ScoreBreakdown`
  - `validate_option_card(card: OptionCard) -> None`
- Produces:
  - `generate_research_options(snapshot: IncentiveSnapshot, max_options: int = 5) -> list[OptionCard]`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_research_planner.py`:

```python
import unittest

from wqb.principle_model import IncentiveSnapshot, SourceEvidence
from wqb.research_planner import generate_research_options


class ResearchPlannerTest(unittest.TestCase):
    def test_generate_research_options_prioritizes_visible_incentives(self):
        snapshot = IncentiveSnapshot(
            generated_at="2026-07-09T00:00:00Z",
            account={"geniusLevel": "GOLD", "onboarding": {"status": "CONSULTANT_APPROVED"}},
            activities=[{"id": "E1", "title": "Opportunity Webinar", "description": "Brain Community Score"}],
            competitions=[
                {
                    "id": "PAC2026",
                    "name": "Python Alphas Competition 2026",
                    "status": "ACCEPTED",
                    "endDate": "2026-07-12T23:59:59-04:00",
                    "leaderboard": {"alphas": 0, "score": 0.0},
                }
            ],
            power_pool_boards=[{"value": "lyvRddy", "label": "USA/D1 Power Pool July'26"}],
            rule_pages={
                "brain-genius": "signal submissions pyramids Combined Alpha Performance",
                "osmosis-allocation-guide-consultants": "Daily Osmosis Rank Combined Osmosis Performance",
                "multiplier-rules": "Themes increase QualityFactor base payment",
                "getting-started-power-pool-alphas": "Power Pool Alphas are simpler",
            },
            evidence=[SourceEvidence("api", "/users/self", "User account state", "2026-07-09T00:00:00Z")],
            refresh_errors=[],
        )

        options = generate_research_options(snapshot, max_options=5)
        titles = [option.title for option in options]

        self.assertGreaterEqual(len(options), 3)
        self.assertTrue(any("Power Pool" in title for title in titles))
        self.assertTrue(any("Genius" in title or "Osmosis" in title for title in titles))
        self.assertTrue(any("Python" in title or "Competition" in title for title in titles))
        self.assertGreaterEqual(options[0].score.total, options[-1].score.total)

    def test_generate_research_options_marks_refresh_uncertainty(self):
        snapshot = IncentiveSnapshot(
            generated_at="2026-07-09T00:00:00Z",
            account={},
            activities=[],
            competitions=[],
            power_pool_boards=[],
            rule_pages={},
            evidence=[SourceEvidence("cache", "knowledge/raw/last_snapshot.json", "Cached snapshot", "2026-07-01T00:00:00Z", stale=True)],
            refresh_errors=[{"path": "/events", "error": "Timeout", "message": "network timeout"}],
        )

        options = generate_research_options(snapshot, max_options=5)

        self.assertEqual(options[0].primary_incentive, "knowledge_refresh")
        self.assertIn("refresh", options[0].title.lower())


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests to verify failure**

Run:

```powershell
python -m unittest tests.test_research_planner -v
```

Expected: fail with `ModuleNotFoundError: No module named 'wqb.research_planner'`.

- [ ] **Step 3: Implement `wqb/research_planner.py`**

Create `wqb/research_planner.py`:

```python
from wqb.principle_model import IncentiveSnapshot, OptionCard, ScoreBreakdown, SourceEvidence, validate_option_card


GENIUS_BASE_SCORE = 7.0
OSMOSIS_BASE_SCORE = 6.5
POWER_POOL_BASE_SCORE = 7.5
THEME_BASE_SCORE = 6.0
COMPETITION_BASE_SCORE = 5.5
REFRESH_RECOVERY_SCORE = 10.0


def _source(snapshot: IncentiveSnapshot, path_fragment: str, fallback_title: str) -> SourceEvidence:
    """Input: snapshot and path fragment. Output: SourceEvidence. Pick the most relevant evidence row."""
    for item in snapshot.evidence:
        if path_fragment in item.path:
            return item
    return SourceEvidence("snapshot", path_fragment, fallback_title, snapshot.generated_at, stale=bool(snapshot.refresh_errors))


def _score(total: float, name: str, reason: str, penalty_name: str = "", penalty: float = 0.0) -> ScoreBreakdown:
    """Input: score values. Output: ScoreBreakdown. Build a consistent one-option score record."""
    penalties = {penalty_name: penalty} if penalty_name else {}
    return ScoreBreakdown(total=total - penalty, components={name: total}, penalties=penalties, reasons=[reason])


def _refresh_recovery_option(snapshot: IncentiveSnapshot) -> OptionCard:
    """Input: IncentiveSnapshot. Output: OptionCard. Create a fallback option when live rules are uncertain."""
    card = OptionCard(
        title="Refresh platform rules before research",
        primary_incentive="knowledge_refresh",
        secondary_incentives=["risk_control"],
        why_now="Live rule refresh produced errors, so current activity choices may be stale.",
        candidate_scope="No alpha research scope until official rules are refreshed.",
        expected_asset_value="Prevents spending API budget under stale incentive assumptions.",
        correlation_risk="No alpha generation happens in this option.",
        resource_cost="Read-only API refresh and local cache update.",
        evidence=snapshot.evidence or [SourceEvidence("local", "knowledge", "Local knowledge cache", snapshot.generated_at, stale=True)],
        failure_modes=["Network access remains unavailable.", "Platform endpoint schema changes."],
        decision_needed="Choose whether to retry refresh or proceed with stale-cache warnings.",
        score=_score(REFRESH_RECOVERY_SCORE, "refresh_required", "Official source refresh failed."),
    )
    validate_option_card(card)
    return card


def _genius_osmosis_option(snapshot: IncentiveSnapshot) -> OptionCard:
    """Input: IncentiveSnapshot. Output: OptionCard. Create the long-term pool-building option."""
    genius_level = snapshot.account.get("geniusLevel", "unknown")
    total = GENIUS_BASE_SCORE + OSMOSIS_BASE_SCORE
    card = OptionCard(
        title="Build Genius and Osmosis alpha pool",
        primary_incentive="genius_osmosis",
        secondary_incentives=["quarterly_payment", "portfolio_structure"],
        why_now=f"Current visible Genius level is {genius_level}; platform rules value signals, pyramids, and combined performance.",
        candidate_scope="Generate a later concrete plan across multiple region-delay scopes after user selection.",
        expected_asset_value="Improves long-term pool diversity for Genius and Osmosis allocation.",
        correlation_risk="Medium; must enforce data, template, operator, and neutralization diversity before simulation.",
        resource_cost="Planning only now; later execution should use 30-alpha batches and multisimulation packing.",
        evidence=[_source(snapshot, "brain-genius", "Brain Genius"), _source(snapshot, "osmosis", "Osmosis Allocation")],
        failure_modes=["Insufficient submitted alpha count per Osmosis scope.", "Pool diversity improves slowly."],
        decision_needed="Choose this if the next run should optimize long-term consultant pool value.",
        score=_score(total, "genius_osmosis_value", "Genius and Osmosis are durable consultant incentives."),
    )
    validate_option_card(card)
    return card


def _power_pool_option(snapshot: IncentiveSnapshot) -> OptionCard | None:
    """Input: IncentiveSnapshot. Output: OptionCard or None. Create Power Pool option when boards are visible."""
    if not snapshot.power_pool_boards:
        return None
    labels = ", ".join(board["label"] for board in snapshot.power_pool_boards[:3])
    score = POWER_POOL_BASE_SCORE + min(len(snapshot.power_pool_boards), 3)
    card = OptionCard(
        title="Explore current Power Pool boards",
        primary_incentive="power_pool",
        secondary_incentives=["theme", "genius", "regular_submission"],
        why_now=f"Visible Power Pool boards include: {labels}.",
        candidate_scope="Choose a board first; only then select matching region, delay, data, and simple templates.",
        expected_asset_value="May create simpler alpha assets with lower submission criteria and reusable rationale.",
        correlation_risk="Medium-high if common fields or templates are crowded; must prefer new data and simple distinct logic.",
        resource_cost="Planning only now; later execution should build 30 candidates per selected board where feasible.",
        evidence=[_source(snapshot, "power-pool", "Power Pool boards")],
        failure_modes=["Pure Power Pool theme mismatch.", "Daily or monthly pure Power Pool quota limits.", "Power Pool correlation failure."],
        decision_needed="Choose this if the next run should target currently visible Power Pool opportunities.",
        score=_score(score, "power_pool_value", "Power Pool boards are visible and can serve multiple incentives."),
    )
    validate_option_card(card)
    return card


def _theme_option(snapshot: IncentiveSnapshot) -> OptionCard | None:
    """Input: IncentiveSnapshot. Output: OptionCard or None. Create Theme multiplier option when rules mention themes."""
    theme_text = snapshot.rule_pages.get("multiplier-rules", "").lower()
    if "theme" not in theme_text and "qualityfactor" not in theme_text.lower():
        return None
    card = OptionCard(
        title="Check active Theme multiplier opportunities",
        primary_incentive="theme",
        secondary_incentives=["base_payment", "power_pool"],
        why_now="Official multiplier rules state Theme-qualified alphas can raise QualityFactor.",
        candidate_scope="Refresh active theme announcements before choosing data or templates.",
        expected_asset_value="Can improve base payment exposure if the resulting alpha also has durable pool quality.",
        correlation_risk="Unknown until the active theme and common crowding patterns are identified.",
        resource_cost="Read-only theme discovery first; simulation budget only after user selects this option.",
        evidence=[_source(snapshot, "multiplier-rules", "Multiplier Rules")],
        failure_modes=["No active theme is available.", "Theme field is crowded.", "Theme alpha fails regular checks."],
        decision_needed="Choose this if the next run should inspect and exploit current Theme multipliers.",
        score=_score(THEME_BASE_SCORE, "theme_multiplier_value", "Theme rules can increase QualityFactor."),
    )
    validate_option_card(card)
    return card


def _competition_option(snapshot: IncentiveSnapshot) -> OptionCard | None:
    """Input: IncentiveSnapshot. Output: OptionCard or None. Create competition option for accepted visible competitions."""
    accepted = [item for item in snapshot.competitions if str(item.get("status", "")).upper() == "ACCEPTED"]
    if not accepted:
        return None
    comp = accepted[0]
    name = str(comp.get("name") or comp.get("id") or "Accepted competition")
    card = OptionCard(
        title=f"Feasibility check for {name}",
        primary_incentive="competition",
        secondary_incentives=["learning", "tooling"],
        why_now=f"Competition is visible as ACCEPTED with end date {comp.get('endDate', 'unknown')}.",
        candidate_scope="Do not select data or templates until competition submission feasibility is verified.",
        expected_asset_value="Can create reusable competition/Python alpha workflow if feasible.",
        correlation_risk="Unknown; competition-specific alphas still need novelty and check gates.",
        resource_cost="One read-only feasibility pass first; no alpha batch before user confirms.",
        evidence=[_source(snapshot, "/competitions", "Competitions")],
        failure_modes=["Competition submissions are disabled.", "Python alpha tooling takes too much setup time.", "Deadline is too close."],
        decision_needed="Choose this if the next run should spend a short feasibility slot on the active competition.",
        score=_score(COMPETITION_BASE_SCORE, "competition_expected_value", "Accepted competition is visible."),
    )
    validate_option_card(card)
    return card


def generate_research_options(snapshot: IncentiveSnapshot, max_options: int = 5) -> list[OptionCard]:
    """Input: IncentiveSnapshot and limit. Output: option cards. Score current research choices without planning batches."""
    if snapshot.refresh_errors and not (snapshot.activities or snapshot.competitions or snapshot.power_pool_boards or snapshot.rule_pages):
        return [_refresh_recovery_option(snapshot)]

    options: list[OptionCard] = [_genius_osmosis_option(snapshot)]
    for maybe_option in [_power_pool_option(snapshot), _theme_option(snapshot), _competition_option(snapshot)]:
        if maybe_option is not None:
            options.append(maybe_option)
    options.sort(key=lambda card: card.score.total, reverse=True)
    return options[: max(max_options, 1)]
```

- [ ] **Step 4: Run the tests to verify pass**

Run:

```powershell
python -m unittest tests.test_research_planner tests.test_rule_refresh tests.test_principle_model -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

Run:

```powershell
git add BrainWorkflow/wqb/research_planner.py BrainWorkflow/tests/test_research_planner.py
git commit -m "add principle led option scoring"
```

Expected: commit succeeds.

---

### Task 4: Decision Logging

**Files:**
- Create: `wqb/decision_log.py`
- Test: `tests/test_decision_log.py`

**Interfaces:**
- Consumes:
  - `OptionCard`
  - `option_card_to_dict(card: OptionCard) -> dict[str, Any]`
- Produces:
  - `write_option_cards(output_dir: Path, cards: list[OptionCard], generated_at: str) -> tuple[Path, Path]`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_decision_log.py`:

```python
import json
import tempfile
import unittest
from pathlib import Path

from wqb.decision_log import write_option_cards
from wqb.principle_model import OptionCard, ScoreBreakdown, SourceEvidence


class DecisionLogTest(unittest.TestCase):
    def test_write_option_cards_creates_jsonl_and_markdown(self):
        card = OptionCard(
            title="Build Genius and Osmosis alpha pool",
            primary_incentive="genius_osmosis",
            secondary_incentives=["quarterly_payment"],
            why_now="Genius rules value signals and pyramids.",
            candidate_scope="Multiple scopes after selection.",
            expected_asset_value="Long-term pool diversity.",
            correlation_risk="Medium.",
            resource_cost="Read-only planning.",
            evidence=[SourceEvidence("api", "/tutorial-pages/brain-genius", "Brain Genius", "2026-07-09T00:00:00Z")],
            failure_modes=["Pool diversity takes time."],
            decision_needed="Choose this option.",
            score=ScoreBreakdown(total=9.0, components={"genius": 9.0}, penalties={}, reasons=["Durable incentive."]),
        )
        with tempfile.TemporaryDirectory() as tmp:
            jsonl_path, md_path = write_option_cards(Path(tmp), [card], "2026-07-09T00:00:00Z")

            rows = [json.loads(line) for line in jsonl_path.read_text(encoding="utf-8").splitlines()]
            markdown = md_path.read_text(encoding="utf-8")

        self.assertEqual(rows[0]["title"], "Build Genius and Osmosis alpha pool")
        self.assertIn("Build Genius and Osmosis alpha pool", markdown)
        self.assertIn("Decision Needed", markdown)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests to verify failure**

Run:

```powershell
python -m unittest tests.test_decision_log -v
```

Expected: fail with `ModuleNotFoundError: No module named 'wqb.decision_log'`.

- [ ] **Step 3: Implement `wqb/decision_log.py`**

Create `wqb/decision_log.py`:

```python
import json
from pathlib import Path

from wqb.principle_model import OptionCard, option_card_to_dict


OPTION_CARD_JSONL = "research_option_cards.jsonl"
OPTION_CARD_MARKDOWN = "research_option_cards.md"


def _card_markdown(card: OptionCard, index: int) -> str:
    """Input: option card and index. Output: markdown string. Render one option card for review."""
    evidence_rows = "\n".join(f"- `{item.path}`: {item.title}" for item in card.evidence)
    failure_rows = "\n".join(f"- {item}" for item in card.failure_modes)
    return (
        f"## Option {index}: {card.title}\n\n"
        f"- Primary Incentive: `{card.primary_incentive}`\n"
        f"- Secondary Incentives: {', '.join(card.secondary_incentives) or 'none'}\n"
        f"- Score: {card.score.total}\n\n"
        f"### Why Now\n{card.why_now}\n\n"
        f"### Candidate Scope\n{card.candidate_scope}\n\n"
        f"### Expected Asset Value\n{card.expected_asset_value}\n\n"
        f"### Correlation Risk\n{card.correlation_risk}\n\n"
        f"### Resource Cost\n{card.resource_cost}\n\n"
        f"### Evidence\n{evidence_rows}\n\n"
        f"### Failure Modes\n{failure_rows}\n\n"
        f"### Decision Needed\n{card.decision_needed}\n"
    )


def write_option_cards(output_dir: Path, cards: list[OptionCard], generated_at: str) -> tuple[Path, Path]:
    """Input: output directory, cards, timestamp. Output: JSONL and Markdown paths. Persist option cards."""
    output_dir.mkdir(parents=True, exist_ok=True)
    jsonl_path = output_dir / OPTION_CARD_JSONL
    markdown_path = output_dir / OPTION_CARD_MARKDOWN

    with jsonl_path.open("w", encoding="utf-8") as handle:
        for card in cards:
            row = option_card_to_dict(card)
            row["generated_at"] = generated_at
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")

    markdown = [f"# Research Option Cards\n\nGenerated at: `{generated_at}`\n"]
    for index, card in enumerate(cards, start=1):
        markdown.append(_card_markdown(card, index))
    markdown_path.write_text("\n\n".join(markdown), encoding="utf-8")
    return jsonl_path, markdown_path
```

- [ ] **Step 4: Run the tests to verify pass**

Run:

```powershell
python -m unittest tests.test_decision_log tests.test_research_planner tests.test_rule_refresh tests.test_principle_model -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

Run:

```powershell
git add BrainWorkflow/wqb/decision_log.py BrainWorkflow/tests/test_decision_log.py
git commit -m "add research option logging"
```

Expected: commit succeeds.

---

### Task 5: Read-Only CLI Command

**Files:**
- Modify: `wqb/cli.py`
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes:
  - `build_client(config: dict[str, Any]) -> WQBClient`
  - `refresh_incentive_snapshot(client: Any, generated_at: str) -> IncentiveSnapshot`
  - `generate_research_options(snapshot: IncentiveSnapshot, max_options: int) -> list[OptionCard]`
  - `write_option_cards(output_dir: Path, cards: list[OptionCard], generated_at: str) -> tuple[Path, Path]`
- Produces:
  - CLI command `plan-research-options`
  - Function `plan_research_options(config: dict[str, Any], max_options: int, output_dir: str) -> dict[str, Any]`

- [ ] **Step 1: Add failing CLI tests**

Extend `tests/test_cli.py` by adding this method inside the existing `CliTests(unittest.TestCase)` class:

```python
from pathlib import Path
from unittest.mock import patch

from wqb.principle_model import IncentiveSnapshot, SourceEvidence


def test_plan_research_options_writes_cards_without_simulation(self):
    from wqb.cli import plan_research_options

    snapshot = IncentiveSnapshot(
        generated_at="2026-07-09T00:00:00Z",
        account={"geniusLevel": "GOLD"},
        activities=[],
        competitions=[],
        power_pool_boards=[{"value": "lyvRddy", "label": "USA/D1 Power Pool July'26"}],
        rule_pages={"brain-genius": "signals pyramids", "getting-started-power-pool-alphas": "Power Pool"},
        evidence=[SourceEvidence("api", "/users/self", "User account state", "2026-07-09T00:00:00Z")],
        refresh_errors=[],
    )

    class FakeClient:
        pass

    with tempfile.TemporaryDirectory() as tmp:
        with patch("wqb.cli.build_client", return_value=FakeClient()), patch(
            "wqb.cli.refresh_incentive_snapshot", return_value=snapshot
        ):
            result = plan_research_options({"request_timeout_seconds": 1}, max_options=3, output_dir=tmp)

        self.assertGreaterEqual(result["option_count"], 1)
        self.assertTrue(Path(result["jsonl_path"]).exists())
        self.assertTrue(Path(result["markdown_path"]).exists())
```

- [ ] **Step 2: Run the focused CLI test to verify failure**

Run:

```powershell
python -m unittest tests.test_cli -v
```

Expected: fail because `plan_research_options` is not defined.

- [ ] **Step 3: Modify `wqb/cli.py` imports**

Add near existing imports:

```python
from datetime import timezone

from wqb.decision_log import write_option_cards
from wqb.rule_refresh import refresh_incentive_snapshot
from wqb.research_planner import generate_research_options
```

If `datetime` is already imported, change the existing import to:

```python
from datetime import datetime, timezone
```

- [ ] **Step 4: Add `plan_research_options` function**

Add near other command functions:

```python
def plan_research_options(config: dict[str, Any], max_options: int, output_dir: str) -> dict[str, Any]:
    """Input: config, option limit, output dir. Output: summary dict. Generate read-only research option cards."""
    generated_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    client = build_client(config)
    snapshot = refresh_incentive_snapshot(client, generated_at=generated_at)
    cards = generate_research_options(snapshot, max_options=max_options)
    jsonl_path, markdown_path = write_option_cards(Path(output_dir), cards, generated_at)
    return {
        "generated_at": generated_at,
        "option_count": len(cards),
        "jsonl_path": str(jsonl_path),
        "markdown_path": str(markdown_path),
        "refresh_error_count": len(snapshot.refresh_errors),
        "options": [card.title for card in cards],
    }
```

- [ ] **Step 5: Extend argparse command choices and arguments**

Add `plan-research-options` to the command choices list.

Add parser arguments:

```python
    parser.add_argument("--max-options", type=int, default=5)
    parser.add_argument("--option-output-dir", default="knowledge/wiki/70_decisions")
```

Add dispatcher branch:

```python
    elif args.command == "plan-research-options":
        result = plan_research_options(config, args.max_options, args.option_output_dir)
        print(json.dumps(result, ensure_ascii=False, indent=2))
```

- [ ] **Step 6: Run tests to verify pass**

Run:

```powershell
python -m unittest tests.test_cli tests.test_decision_log tests.test_research_planner tests.test_rule_refresh tests.test_principle_model -v
```

Expected: all tests pass.

- [ ] **Step 7: Commit**

Run:

```powershell
git add BrainWorkflow/wqb/cli.py BrainWorkflow/tests/test_cli.py
git commit -m "add read only research planner cli"
```

Expected: commit succeeds.

---

### Task 6: Knowledge Pages And Operational Rules

**Files:**
- Create: `knowledge/wiki/00_principles/principle_stack.md`
- Create: `knowledge/wiki/70_decisions/README.md`
- Modify: `knowledge/wiki/index.md`
- Modify: `docs/knowledge/wqb_rules.md`
- Test: use file existence and placeholder scan commands.

**Interfaces:**
- Consumes: design spec and CLI output locations.
- Produces: stable wiki landing pages for principles and decisions.

- [ ] **Step 1: Create principle stack wiki page**

Create `knowledge/wiki/00_principles/principle_stack.md`:

```markdown
# Principle Stack

The Phase 2 workflow starts from durable consultant incentives before choosing activities, regions, data, templates, or alpha batches.

## Core Metrics

- Consultant incentive value: dormancy safety, Genius, Osmosis, Theme, Power Pool, competition, and quarterly payment potential.
- Alpha asset quality: checks passed, performance margin, stable PnL, low correlation, investability, and economic clarity.
- Portfolio structure value: region-delay scope coverage, dataset diversity, operator diversity, turnover diversity, and drawdown diversification.
- Research efficiency and learning: submit-ready hit rate, repair success rate, scout discovery rate, recovery rate, and reusable knowledge gain.

## Gates

1. Refresh platform rules and account state.
2. Generate option cards.
3. Ask the user to choose.
4. Generate a concrete plan only for the chosen option.
5. Run simulations or checks only after the plan is selected.
6. Promote only alphas that pass all required platform checks.
7. Update benchmarks and knowledge after every meaningful result.
```

- [ ] **Step 2: Create decision log README**

Create `knowledge/wiki/70_decisions/README.md`:

```markdown
# Decision Logs

This directory stores generated research option cards and user choices.

Each workflow start should create:

- `research_option_cards.jsonl`
- `research_option_cards.md`

The user-selected option should be recorded before any concrete research plan is generated.
```

- [ ] **Step 3: Update wiki index**

Add these lines to `knowledge/wiki/index.md`:

```markdown
- [[00_principles/principle_stack|Principle Stack]]
- [[70_decisions/README|Decision Logs]]
```

- [ ] **Step 4: Update operational rules**

Append to `docs/knowledge/wqb_rules.md`:

```markdown
## Phase 2 Principle-Led Planning

- Before each workflow start, refresh platform rules, activities, competitions, Power Pool boards, themes, account state, and relevant data metadata.
- Generate 3-5 option cards before any concrete alpha batch plan.
- The user must choose one option before the system creates activity, region, delay, dataset, template, or batch instructions.
- If refresh fails, show stale-cache warnings and prefer a refresh-recovery option.
- Do not run simulations or submissions from the option-card planner.
```

- [ ] **Step 5: Verify docs**

Run:

```powershell
Test-Path knowledge/wiki/00_principles/principle_stack.md
Test-Path knowledge/wiki/70_decisions/README.md
$patterns = @('T' + 'BD', 'TO' + 'DO', 'PLACE' + 'HOLDER', '待' + '定')
Select-String -Path knowledge/wiki/00_principles/principle_stack.md,knowledge/wiki/70_decisions/README.md,docs/knowledge/wqb_rules.md -Pattern $patterns -CaseSensitive
```

Expected:

```text
True
True
```

and no placeholder matches.

- [ ] **Step 6: Commit**

Run:

```powershell
git add BrainWorkflow/knowledge/wiki/00_principles/principle_stack.md BrainWorkflow/knowledge/wiki/70_decisions/README.md BrainWorkflow/knowledge/wiki/index.md BrainWorkflow/docs/knowledge/wqb_rules.md
git commit -m "document principle led planning workflow"
```

Expected: commit succeeds.

---

### Task 7: Full Verification And Publish

**Files:**
- Verify all files changed in previous tasks.

**Interfaces:**
- Consumes: all previous tasks.
- Produces: pushed branch or a clear authentication blocker.

- [ ] **Step 1: Run full unit tests**

Run:

```powershell
python -m unittest discover -s tests -v
```

Expected: all tests pass.

- [ ] **Step 2: Run a dry planner command with mocked credentials only when live credentials are available**

If `WQB_USERNAME` and `WQB_PASSWORD` are set, run:

```powershell
python -m wqb.cli plan-research-options --config configs/stage1_usa_d1.yaml --option-output-dir knowledge/wiki/70_decisions --max-options 5
```

Expected: JSON output with `option_count` greater than 0 and paths under `knowledge/wiki/70_decisions`.

If credentials are not set, skip the live command and record: `Skipped live planner command because WQB_USERNAME/WQB_PASSWORD are not set`.

- [ ] **Step 3: Check git status**

Run from `C:\Users\oytl\Desktop\pyproject\brain\skills-and-workflows`:

```powershell
git status -sb
```

Expected: clean branch after commits.

- [ ] **Step 4: Push branch**

Run:

```powershell
git -c http.proxy=http://127.0.0.1:7890 -c https.proxy=http://127.0.0.1:7890 push -u origin agent/brainworkflow-phase2
```

Expected: branch pushed. If authentication fails, stop and ask the user to provide a GitHub push path or install/authenticate `gh`.

- [ ] **Step 5: Draft PR creation path**

Because GitHub CLI is not installed in the current environment, use one of these verified paths:

```powershell
git remote -v
git branch --show-current
```

If the GitHub connector exposes PR creation in the active tool list, create a draft PR targeting `main`. If it does not, report the pushed branch and give the exact compare URL:

```text
https://github.com/oytl2024/skills-and-workflows/compare/main...agent/brainworkflow-phase2
```

Expected: user can open or review the branch.

---

## Self-Review Checklist

- Spec coverage:
  - Rule refresh is covered by Task 2.
  - Option cards are covered by Task 3.
  - User-choice gate is represented in option card contract and docs.
  - Concrete alpha planning is intentionally excluded.
  - Knowledge outputs are covered by Tasks 4 and 6.
  - No simulation or submission action is included.
- Placeholder scan:
  - This plan avoids the forbidden placeholder markers listed in the writing-plans skill.
- Type consistency:
  - `IncentiveSnapshot`, `OptionCard`, `SourceEvidence`, and `ScoreBreakdown` are defined in Task 1 and reused by later tasks.
  - `generate_research_options` returns `list[OptionCard]`.
  - `write_option_cards` returns `tuple[Path, Path]`.
  - CLI function returns `dict[str, Any]`.
