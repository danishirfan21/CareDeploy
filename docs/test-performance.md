# Backend test performance

All figures are from one machine (Windows 10, local PostgreSQL 17 on port 5433, sequential run, no parallelism). They show where time goes; they are not benchmarks of the product.

## Measurement

`pytest --durations=60` over the full suite on 2026-11-25: **230 passed in 37 min 32 s** (2252 s).

The earlier recorded baseline was 218 tests in 34 min 41 s. The suites are **not comparable**: this run has 12 more tests, including the 165 s lifecycle test and five evaluator mutation tests that each run evaluation scenarios. No before/after speedup is claimed.

Time by file, from the 60 slowest setup/call phases (about 1540 s of the 2252 s):

| File | Seconds | Why |
| --- | --- | --- |
| `test_deployments.py` | 693 | The `evaluated` fixture runs a full 20-scenario evaluation before most tests (45 to 110 s each). |
| `test_evals_runner.py` | 335 | Mutation tests each run a targeted evaluation. |
| `test_lifecycle.py` | 165 | Two full evaluations (version 1 and 2) plus the lifecycle itself. |
| `test_voice_tools.py` | 92 | Per-test world setup. |
| `test_migrations.py` | 64 | Up, down and up again against a real database. |

## Where a full evaluation spends its time

Profiled with a timing wrapper around one 20-scenario run (41 s total):

| Phase | Count | Seconds |
| --- | --- | --- |
| Create and migrate template database | 1 | 1.9 |
| Clone a scenario database from the template | 20 | 12.2 |
| Drop a scenario database | 21 | 18.5 |
| Scenario execution, everything else | | about 8 |

About 75% of an evaluation is creating and dropping databases, which is the isolation that keeps scenarios independent. Cloning from a migrated template is already used; migrating per scenario would be far slower.

## Tried and rejected

**Dropping scenario databases on a background thread** while the next scenario runs. Measured: the same run took 244 s instead of 41 s. Overlapping `DROP DATABASE` with `CREATE DATABASE ... TEMPLATE` serializes on PostgreSQL's checkpoint/locking and is slower, not faster. Reverted; no code change was kept.

## Not changed, and why

- **Sharing one evaluation across the deployment tests.** It would remove most of the 693 s, but those tests mutate evidence, deployments and clocks, and sharing results risks hiding the order-dependent bugs the tests exist to catch. It would need a deliberate design (a read-only evidence snapshot per test) and was not safe to rush.
- **Parallel test processes.** Forbidden: the suite resets a shared test database, and two runs against one database corrupt each other.

## Practical guidance

- Quick loop: run the file you changed. Scheduling, ops and voice files take seconds to a few minutes.
- Before committing: the full suite, sequentially, about 38 minutes on this machine.
- Idea for later: drop `fsync` and use a RAM disk for the test cluster only (not applied; it changes the environment, not the tests).
