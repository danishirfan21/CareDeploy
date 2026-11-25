# Case study: CareDeploy

An independent portfolio project built to demonstrate forward-deployed engineering: taking a general capability (a voice scheduling agent) and making it configurable, verifiable and safely deployable per customer. It is not affiliated with any company, uses sample data only, and makes no claim about any company's internal tooling, commercial results or regulatory compliance.

## Overview

CareDeploy lets an operator configure a clinic once (hours, appointment types, policy, agent behavior), publish an immutable version, evaluate it, promote it, and then watch what calls did. Two sample clinics with different rules run on the same code.

## Problem

A voice agent that books appointments is easy to demo and hard to deploy: each customer has different rules, a wrong booking is costly, and "it worked when I tried it" is not evidence. The project asks: what must be true before a configuration is allowed to take calls, and how can you show it?

## Architecture

FastAPI and PostgreSQL own all state and rules. A Next.js admin UI configures and observes. A separate LiveKit worker speaks to callers but holds no rules: it calls the same backend tool layer the evaluations use. See [`architecture.md`](architecture.md).

## Key decisions

- **One source of truth for scheduling.** Rules live in the backend; the voice worker and the evaluator call the same tools.
- **Immutable published versions** and a deployment pointer, so what a call used can always be reconstructed.
- **Database-enforced invariants** (no overlapping appointments, append-only deployment history) rather than application-only checks.
- **Server-computed readiness.** The browser cannot supply evidence.
- **Honest evidence levels.** Evaluations are labelled "workflow simulation"; real voice verification is a separate, currently pending level.

## Reliability safeguards

Idempotency keys with a proposal-then-confirm flow; exclusion constraint plus a per-clinic advisory lock (found by reproducing a rare deadlock, see [`concurrency-investigation.md`](concurrency-investigation.md)); retry-safe 503s; tenant scoping on every query; a production exposure guard (see [`security.md`](security.md)).

## Evaluation strategy

Twenty-one scenarios run the real tools against isolated databases. The evaluator itself is tested by mutation: tests deliberately break the code (a tool that claims success without writing, an ignored idempotency key, broken scoping) and require the right scenario to fail. That review found a real coverage gap (EVAL-015), which was fixed. A later mutation review found the cancellation-window rule was covered only by unit tests; EVAL-021 now covers it and a mutation test proves that bypassing the rule turns it red.

## Deployment controls

Readiness checks, compare-and-swap promotion, evidence tied to scenario and suite versions with a configurable age limit (30 days, a demo assumption and not an industry requirement), rollback as a new event.

## Measured evidence

Only what was measured, with its limits, is in [`demo-evidence.md`](demo-evidence.md) and [`verification-matrix.md`](verification-matrix.md). No call volumes, savings or accuracy rates are claimed because none were measured.

## Operational traceability and reproducibility

Every call is persisted with its configuration version, transcript, tool activity and the operations it caused, and an outcome class (escalation is not failure; unknown is kept apart). A reviewer can follow a call from the Activity page to the operation ledger and the appointment row in PostgreSQL. Setup is scripted (migrations, seed, one-command test suites), and the GitHub Actions workflow runs lint, strict typing, the backend suite on PostgreSQL, a migration smoke test, the voice-service tests, the frontend checks and Playwright end to end. It does not prove live voice.

## Tradeoffs

Per-clinic serialization of bookings trades peak throughput for correctness. Workflow-simulation evaluation is cheap and repeatable but cannot judge model behavior. No user authentication: the admin API must sit behind access control.

## Limitations

Live voice, speech quality, barge-in, model-driven evaluation and Docker Compose are unverified (see the matrix). The GitHub Actions workflow has run remotely and passed (after one real failure on its first run, a missing generated-types step, which was fixed); it deliberately excludes live voice. Not a HIPAA-compliant system; no real patient data should be used.

## Relevance to forward-deployed work

The project exercises the loop an FDE repeats per customer: capture their rules as configuration, prove behavior before go-live, control rollout and rollback, observe real outcomes, and be explicit about what is not yet proven.
