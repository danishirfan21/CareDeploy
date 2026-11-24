# CareDeploy v1.0 — Product Specification

CareDeploy is a multi-clinic AI voice-agent deployment platform. It is a portfolio project for a Forward Deployed Engineer role. It demonstrates:

1. Reusable clinic onboarding.
2. Configuration-driven voice agents.
3. Reliable scheduling operations.
4. Automated evaluations.
5. Operational visibility.

## UX direction
Minimal, ChatGPT-inspired workspace: collapsible sidebar, generous whitespace, restrained teal accent. Three primary destinations: **Clinics**, **Playground**, **Activity**. Google Stitch designs are the visual reference; exports are not in `design/` yet, so the shell is a restrained implementation, with no claim of visual fidelity. Features that are not built are labelled unavailable, never faked.

## Functional modules
| Module | Summary |
|---|---|
| Clinics & configuration | Multi-clinic CRUD; five-step wizard (details, hours and services, scheduling rules, agent behavior, review and publish); drafts; immutable published versions. |
| Scheduling operations | Availability, booking, cancellation and rescheduling that enforce a clinic's published configuration. |
| Voice Playground | Exercise a clinic's agent against its published configuration. |
| Evaluations | Automated scenario runs scored against a clinic's configuration. |
| Activity | Operational visibility: configuration changes, publishes, scheduling operations, evaluation runs, and simulated deployment promotion. |

## Milestones
- **M0** Foundation: monorepo, tooling, health connectivity, migrations, CI. *(done)*
- **M1** Multi-clinic management and configuration: shell, clinic CRUD, wizard, drafts, immutable versions, two seeded clinics.
- **M2** Scheduling operations driven by published configuration.
- **M3** Voice Playground.
- **M4** Evaluations.
- **M5** Activity and simulated deployment promotion.
- **M6** Hardening, auth, deployment, documentation, v1.0.

## Exclusions (v1.0)
- Real patient data, PHI, or HIPAA compliance claims. All clinics are fictional.
- Real telephony or production deployment of live agents. Publishing a configuration version does **not** make a live voice agent available.
- Enterprise dashboards, KPI grids, billing, role administration.
- A general-purpose AI assistant input.

## M1 acceptance criteria
1. Both seeded clinics (Northstar Family Medicine, Lakeside Dermatology) are shown with distinct configurations.
2. A third clinic can be created.
3. The five-step wizard can be completed, one step at a time, with Back, Continue and Save.
4. Settings persist across application restarts (PostgreSQL).
5. Clinic configurations are isolated from each other.
6. An immutable configuration version can be published; published versions cannot be modified, enforced in the database.
7. Backend and Playwright tests pass against real API and database.
8. Migrations are additive and run successfully.
9. M0 tests still pass.
10. Documentation reflects the implementation.
