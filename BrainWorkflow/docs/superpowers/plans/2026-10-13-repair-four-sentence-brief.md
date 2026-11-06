# Repair Four-Sentence Brief Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans or superpowers:subagent-driven-development.

**Goal:** Default each Alpha Repair model input to four single-sentence sections without losing immutable detailed evidence.

**Architecture:** Deterministic planner builds strategy/problem/history/task sentences and persists full evidence separately. Worker renders the brief and provenance pointers only; read-only Codex can consult run-local detailed evidence and the immutable knowledge snapshot. Existing receipt validation and legacy consumed plans remain unchanged.

**Tech Stack:** Python standard library, unittest, existing Codex CLI checkpoint worker.

**Spec:** User-confirmed maintenance conversation, 2026-10-13: exactly one sentence per brief section; knowledge/evidence read-only on demand.

## Constraints
- No WQB, real model calls, research resume, quota changes, commits or final submission during offline maintenance.
- Keep 9000-character default rendered evidence cap, not an advertised token or billing cap.
- Preserve raw evidence, original digest bindings, Stop and legacy immutable plans.
- Read-only sandbox does not constitute a filesystem read allowlist; do not claim it does.
- Do not infer economic meaning or thresholds absent authoritative evidence.

## Tasks
- [x] RED/GREEN planner tests: large metrics/history accepted as supporting evidence, exactly four sentence sections, no missing adverse-check concealment, restart provenance.
- [x] RED/GREEN worker tests: prompt uses brief only, complete Unicode/JSON, explicit oversized handling, supporting path/digest checks.
- [x] Integrate, run focused/full offline regressions, update architecture/operator documentation and durable handoff.
- [x] Verify current maintenance case through source-bound verification and loaded Console state; do not resume research.

## Acceptance

Final source-bound verification: 1394 tests passed, returncode0, unchanged source,
no failures; case d9264de3ae65bdf2515d486a resolved. Backend48652 loaded revision
d7ccb4119f046703d3eea227473fa38bfcc19434c837ba219e6cbfb146e981c8;
Continue/Stop enabled. Exact legacy planning-pause lineage recovery was tested
offline and actual receipt eligibility checked read-only. No real model/platform
calls, research resume, simulation or budget changes. Live quality remains unverified.

## Review Focus
- Oversized expressions and failure lists must be referenced explicitly, not silently discarded.
- Unknown semantics, thresholds and historical comparisons remain marked unknown.
- Mutable or outside-run supporting paths cannot impersonate immutable evidence.
- Legacy receipts remain verifiable; new brief changes naturally create new input identity.
- Multi-byte UTF-8 must not be sliced into invalid JSON or replacement characters.
