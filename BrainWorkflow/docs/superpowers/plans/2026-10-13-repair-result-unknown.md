# Repair Result-Unknown Isolation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans.

**Goal:** Isolate an already-submitted simulation whose progress returned404 without resubmission, quota refund or invented results.

**Architecture:** Bind result-unknown evidence to exact persistent plan/submission journal. Runtime distinguishes poll404 from auth/check/429 failures; scheduler isolates only verified unknown attempts and excludes them from replanning while other parents advance. Adapter validates original lineage before migration; restart rechecks quarantine evidence.

**Spec:** Human-confirmed quarantine/limited-read policy for case79f1fd163ed1272f49d4e604.

**Constraints:** No new simulation/model calls, research resume, quota changes or final submission during maintenance. Local original-identity evidence first; no broad platform search. A possible single remeasurement requires separate explicit authority and must never replay the old POST.

- [x] RED/GREEN bound evidence, poll404 classification, restart and conflict negatives.
- [x] RED/GREEN scheduler isolation/independent progression and adapter import lineage.
- [x] Full source-bound verification, loaded Console/actions and durable handoff.

## Acceptance

1424tests passed with unchanged source, returncode0/no failures; case79f1fd163ed1272f49d4e604 resolved.
Medium final scoped review found no residual issues. Backend51284 matches source
revisionaf9848fc3d79317a88758e6804cff73d3ed6d5f5ec83c931d29bb5439104a088;
Continue/Stop enabled. Local original-identity reconciliation prepared unknown
evidence with original files unchanged; normal Resume performs phase migration.
No new model/platform requests, research resume, simulation or quota changes.
Remeasurement remains separately authorized and is not enabled by Resume.
