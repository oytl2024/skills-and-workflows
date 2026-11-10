# Repair Output Contract Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans or superpowers:subagent-driven-development.

**Goal:** Prevent ambiguous model command fields and recover completed unambiguous judgments without duplicate model/simulation work.

**Architecture:** Worker emits strict paired action/edit/value schema. Planner preserves raw rejected receipt and validates a separate derived normalization receipt, bound to source digest and identical evidence. Adapter admits only exact known planning failures with verified append-only lineage; legacy consumed receipts stay untouched.

**Spec:** Human-confirmed proposal for case111d9d7cb9360fcd67ba201e, 2026-10-13.

**Tech Stack:** Python standard library, existing checkpoint/receipt contracts, unittest.

## Constraints
- No real model/WQB calls, research resume, budget changes, submission or commits.
- Never overwrite rejected judgments or infer strategy changes from arbitrary prose.
- Stop is effect-free; test recovery requires exact action/value and matching single-edit instruction.
- Preserve snapshot/support integrity, Stop, parent identity and duplicate checks.

## Tasks
- [x] RED/GREEN strict worker schema and paired command regression.
- [x] RED/GREEN audited normalization, tamper/restart/legacy compatibility and no repeated model call.
- [x] RED/GREEN adapter recovery for this exact planning fault, negative lineage/unknown-error cases.
- [x] Medium review findings addressed, full source-bound verification, loaded Console/action check and final handoff.

## Acceptance

1408 tests passed with unchanged source; case111d9d7cb9360fcd67ba201e resolved.
Backend32840 matches local revision8fcb13356da68707347b2329f4bd1950c8e1249d8496aae09e409024e00abced;
Continue/Stop enabled. Three existing judgments reconciled locally with original
receipts unchanged, no model/platform calls, simulation, resume or budget changes.
Independent review's concrete findings have RED/GREEN regressions; final independent
recheck hit quota, so no final independent sign-off or live schema acceptance is claimed.
