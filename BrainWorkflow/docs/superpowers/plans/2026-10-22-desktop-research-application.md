# Desktop Research Application Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver a readable real-time EXE application for two-lane research, with in-place commands and inspectable experiments.

**Architecture:** One existing Python backend, React+TypeScript view and thin system-WebView host. Reuse SSE with versioned snapshots; UI state is not workflow state. Validate desktop packaging before committing to a host dependency.

**Tech Stack:** React, TypeScript, existing Python312 backend; system WebView subject to offline spike. No Vercel, Electron or Rust introduced by this approval.

**Spec:** ../specs/2026-10-22-preplanned-parallel-research-console-design.md

## Global Constraints

- No WQB/model calls, live resume, budget renewal or Alpha submission in development.
- Chinese-readable Notion-inspired neutral layout, arrow navigation/page count, routine Start/Stop.
- No redirects/raw refused pages or manual refresh in ordinary operation.
- Proposed targets100ms pending/150ms cached lane switch/p95 healthy update1s are measurements to pass, not delivery claims.
- Keep one authoritative backend; preserve Stop/recovery/privacy and existing old-run readers.
- Unknown Alpha IDs stay blank; unavailable metrics have explicit unknown state, never zero substitution.
- Subagents medium or lower; no installation/download outside workspace without applicable approval.

## Review Focus

- Projection throws while SSE remains open: Task2 stale/error watchdog test.
- Click acknowledged late or twice: Task2 command identity/reconciliation test.
- Stop persists before UI sees reply: Task2 distinguishes intent/fence confirmation.
- New snapshots arrive while user reads a long expression: Task3 focus/scroll test.
- EXE launches with no development Python: Task1/4 packaging and child-process test.

## File Map

Reuse wqb/desktop.py, console_server.py, console_start.py, console_state.py,
console_jobs.py, strategy_progress.py and existing tests. New wqb/console_api.py
owns JSON command/read-model adapter only; it calls existing authorized actions.
New frontend/ contains only this product's package.json/lockfile, src and tests;
frontend/dist is generated output, not another project authority. Use existing
scripts/ for builds and output/ for desktop packages/reports. Do not create root
mock profiles, duplicate progress files, extra backend or framework scaffolding.

## Task1: Offline Desktop Host Feasibility

**Files:** scripts/probe_desktop_host.py, tests/test_desktop_host_probe.py;
record result in this plan and existing output/desktop-validation/.

**Interfaces:** probe_host() -> dict returns local runtime/toolchain availability,
supported packaged process entry and no-admin deploy findings; no secrets.

- [ ] Check local system WebView/runtime/build dependencies without installing.
  Test fake unavailable/present results before adding bounded local probe.
- [ ] Validate local assets, Python backend launch/health ownership, packaged process
  entry and application-relative paths on offline fixtures. Distinguish source
  launch success from a self-contained EXE feasibility result.
- [ ] If dependencies absent, report exact choice/download/size and obtain required
  approval; do not substitute Edge app-mode and claim final EXE acceptance.
- [ ] Choose one smallest viable host/toolchain in plan based on evidence; human
  review if dependency/stack changes. Test and commit probe/docs only.

## Task2: Versioned Read Models And In-Place Commands

**Files:** wqb/console_api.py, console_server.py, console_state.py, console_jobs.py;
tests/test_console_api.py, test_console_runtime.py, test_console_start.py.

**Interfaces:** project_group(group: Path) -> dict returns schema/version, server_epoch,
monotonic sequence, evidence time, group/lane IDs, allowed_actions and bounded summaries.
project_node(run: Path, node_id: str) -> dict returns authoritative detailed evidence.
submit_command(paths, command: dict) -> dict returns command_id, status, durable job ID
or structured refusal. Commands bind expected revision and explicit group ID.

- [ ] Write failing tests for duplicate/lost acknowledgment, foreign origin, invalid IDs,
  stale expected revision, Stop races, source mismatch and missing/corrupt evidence.
- [ ] Implement JSON actions using existing handlers/authority, no parallel action
  semantics. Keep compatibility routes for old clients without routing new UI there.
- [ ] Extend existing SSE to complete sequenced snapshots; handle runtime-error,
  heartbeat timeout, reconnect and stale older HTTP replies. Resnapshot on restart/
  epoch change; no event-replay infrastructure unless demonstrated necessary.
- [ ] Keep cold knowledge parsing off hot/action paths; index progress rows by stable
  identity, bound history summaries and fetch details lazily. Measure before/after.
- [ ] Run new suites plus console server/state/runtime/start tests; review/commit.

## Task3: React Research Workspace

**Files:** frontend/package.json, frozen lockfile, tsconfig/build config,
frontend/src/{App.tsx,api.ts,types.ts,styles.css},
frontend/src/components/{WorkflowNavigation.tsx,ExperimentTree.tsx,NodeDetail.tsx,SeedView.tsx,RepairView.tsx};
frontend/tests/interaction tests. Dependency versions resolved/pinned at execution,
verified against official documentation then; no implicit latest installs.

**Interfaces:** consume Task2 snapshots/commands. Local state contains only viewed
lane/stage/node, expansion, focus, scroll and pending command IDs. Server owns all
execution status. Node IDs/lanes stable across updates and process restarts.

- [ ] Write fixture interaction tests first: Start pending/ack/refusal in place,
  group Stop, arrow boundary/page count, both lane statuses and no state mutation
  when navigating. No network to platform even if selecting nodes.
- [ ] Implement neutral white/graphite Chinese system typography, fine separators,
  restrained accent states and aligned metrics; Lucide arrow/tool icons + tooltips.
  Fixed top actions and overview entry. Stage navigation shows inspectable Scout,
  Seed and Repair, not controls requiring human stage advancement.
- [ ] Tree distinguishes selected viewing node from actively executing node; show
  planned/unselected/waiting/recovering/accepted/rejected/inconclusive states with
  labels. Detail shows hypothesis, condition, full expression/settings, raw and
  directional signals, ID, metrics, route/rollback reasons and source references.
- [ ] Repair independent scroll view includes expression/settings/ID/score and
  comparisons; Seed shows retained core and hard-gate/ranking explanation.
- [ ] Test retained focus/scroll/selection on streaming updates; expansion for long
  expressions; blank IDs; keyboard navigation; contrast/text zoom/reduced motion.
- [ ] Browser screenshots at desktop and narrow viewport, inspect real render/no
  overlap. Run TypeScript check/build and interaction suite; review/commit.

## Task4: EXE Integration And Measured Acceptance

**Files:** wqb/desktop.py, scripts/build_desktop.ps1, tests/test_desktop.py,
frontend/tests/end-to-end; operations user/maintainer docs; root milestone/todo.

**Interfaces:** selected Task1 host loads built Task3 assets and existing Task2
local backend. Entry resolves packaged paths, no recursive sys.executable -m
failure. Keep backend ownership/health validation and durable research state.

- [ ] Write lifecycle tests: first launch, second launch, wrong backend revision,
  port busy, missing runtime, source path with spaces/non-ASCII and packaged children.
  Never kill unknown processes to claim automatic upgrade.
- [ ] Package actual clickable exe using validated host; disable unnecessary remote
  content/navigation/native bridge capabilities. Bind server to localhost, validate
  origin/command identity and ensure secret data excluded from assets/diagnostics.
- [ ] Closing view does not silently Stop research or erase authority. Reopen shows
  persisted state. Updates require safe owned-backend lifecycle; worker evidence survives.
- [ ] Offline end-to-end fixture combines both lanes/tree branching/Seed/Repair/
  candidate view with no internal gate clicks, no manual refresh and no real APIs.
- [ ] Measure click->pending, durable acknowledgment, persisted event->view,
  cached lane switch and cold startup separately, p50/p95 with documented history
  size/load/sample counts. Healthy push target1s; disconnected fallback explicitly
  marked. Failed performance target remains an unresolved acceptance item.
- [ ] Run full Python offline suite, frontend build/tests, desktop smoke, independent
  medium review and root architecture/entry tests. Verify loaded revision in actual
  packaged application. Update docs then follow Git sync/audited cleanup rules.

## Execution Gate

### Implementation Evidence (2026-10-23)

- Host selected: pywebview/System WebView2 + PyInstaller, workspace-local pinned
  build dependencies; actual EXE source/child-process/native-window checks pass.
- React typecheck, build and15 interaction/contract tests pass. Desktop1440x1000
  and mobile390x844 projection screenshots have no page errors or overlap.
- Fixture measurements: pending p95=2.6ms, cached lane switch20.8ms,
  SSE-to-view4.2ms (N2/12samples). Real localhost durable Start/Stop receipts
  p95=316.30ms (N2/12samples, fake worker spawning, empty history).
- Three new-profile EXE starts to native window plus backend health:
  2559.79/2555.08/2582.34ms; p50=2559.79ms,p95=2582.34ms,500ms sampling.
  This is not rendered-React completion or large-vault/live-platform latency.
- Exact build/full-suite/review status is in root todo.md. No live deployment,
  legacy-proof renewal or research resume follows from fixture acceptance.
- Open scope: real-resource deployment/migration, large-history profiling and
  hard total HTTP response cancellation remain separate from this offline build.

User reviews this plan and selects subagent-driven or inline execution before code.
Packaging spike is first dependency gate, not permission for arbitrary installs.
Research plan owns execution facts; frontend fixtures can start independently,
but integrated acceptance depends on its verified read models and group authority.
