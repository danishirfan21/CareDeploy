# UI architecture (M2.5)

The frontend follows the Stitch designs exported to `design-reference/{desktop,tablet,mobile}`
(design tokens are described in `design-reference/desktop/caredeploy/DESIGN.md`). The designs were
used as a visual reference; the exported HTML was not pasted into the app. All behaviour, API calls
and tests from M1 and M2 are unchanged.

## Screen to route mapping

| Stitch screen | Route | Notes |
| --- | --- | --- |
| Home workspace | `/` | Welcome and three navigation actions (clinics, playground, evaluations). |
| Clinics | `/clinics` | Clinic cards from the API. Status pill shows `Draft` or `Published vN`. |
| Setup wizard | `/clinics/new`, `/clinics/[id]/configure` | Five steps, one visible at a time. Separate route, not inline under the list. |
| Voice playground | `/playground` | Clinic selector, agent version, Start call, connection status, mic control, End call, live transcript, inline tool activity, verification and confirmation states, after-call outcome. Driven by `useCall` (M3). |
| Call details | `/activity/calls/[id]` | Outcome, duration, transcript, tool activity and operation ids of a finished call. |
| Evaluations | `/evaluations` | Clinic, published version, mode and scenario selectors; Run evaluation; progress with cancel; results grouped by category with real counts; failure inspection; readiness message. Empty state: "Run your first evaluation to check this agent's scheduling behavior." |
| Activity | `/activity` | Calls / Evaluations tabs. The Evaluations tab lists persisted runs for a chosen clinic; the Calls tab has no call list yet. |

`/dev/ui` previews the typed components with clearly labelled sample data (development only, not
linked). `/dev/scheduling` is unchanged.

## Shared components

- Shell: `components/shell.tsx` (sidebar, tablet pill bar, mobile top bar, drawer, bottom tabs).
- Primitives: `components/ui.tsx` (PageHeader, buttons, Field, Notice) and `components/primitives.tsx`
  (StatusIndicator, EmptyState, Card). Icons are inline SVG (`components/icons.tsx`), no icon font.
- `components/clinic-selector.tsx`: ClinicSelector (reads `GET /api/clinics`).
- `components/wizard/wizard-parts.tsx`: WizardProgress, WizardNavigation (wizard logic and
  validation are untouched).
- `components/voice/`: ConversationTranscript, ConversationMessage, ToolActivity, ToolChain,
  CallOutcome, CallControls and their data types (`types.ts`).
- `components/evaluations/evaluation-parts.tsx`: ReadinessPanel, RunProgress, CategoryGroupCard, ResultInspector, RunHistory, status pills. Data shapes come from `lib/api/types.ts`. No percentage or combined score is rendered.
- `components/activity/`: ActivityList, ActivityDetail.

The voice, evaluation and activity components take typed props and contain no data fetching or
sample data, so M3 and M4 can feed them real results without redesign.

## Responsive behaviour

- Desktop (1024px and up): collapsible 260px sidebar (collapses to icons).
- Tablet (768 to 1023px): top bar with pill navigation, matching the tablet export.
- Mobile (below 768px): compact top bar, slide-in drawer (focus moves to its close button, Escape and
  backdrop dismiss it) and a bottom tab bar with safe-area padding. Form controls are 44px high with
  16px text to avoid mobile zoom.

Exactly one navigation labelled "Primary" is visible at any width.

## Intentional departures from Stitch

The exports contain content that would be false in this app, so it is not reproduced:

- Fabricated labels and data: workspace/region chips, "HIPAA enclave", compliance footers, version
  chips, "CareAgent" runtime names, the sample user profile, example conversations, "18 of 20
  scenarios", and sample call history. No such values are shown as real.
- The home task composer and "New Task" buttons: there is no assistant behind them, so they are
  omitted rather than made to look functional. Settings and profile entries are also omitted
  (only Clinics, Playground and Activity are navigable).
- The wizard lives on its own route instead of below the clinic list, and form fields stay as
  labelled inputs (checkbox rows rather than the pill/chip selectors) to keep the existing tested
  behaviour and accessibility.
- Material Symbols are replaced by inline SVG icons.

## Export inconsistencies noted

- The desktop exports show a broken logo image next to the brand text; the tablet export uses a
  teal icon tile. The icon-tile version is used.
- Version chips and region labels differ between screens (`v2.4.0-prod`, `v2.14.0`, `prod-us-east`).
- The tablet export has top navigation while desktop has a sidebar and mobile has a bottom bar; all
  three are implemented as above.

## Verification

Screens were rendered in Chromium at 1440, 768 and 390px wide (`e2e/zzz-visual.spec.ts` writes them
to the git-ignored `apps/web/test-output/screens`) and compared by eye with each export's
`screen.png`. Playwright also asserts no horizontal overflow at tablet and mobile widths. This is a
visual comparison, not a pixel diff, so exact spacing and type metrics differ in places.

## Remaining limitations and integration points

- M3 (done, see `voice-agent.md`): the playground feeds `ConversationTranscript`, `ToolActivity` and
  `CallControls` from the backend event log through `src/lib/voice/use-call.ts` and `fold.ts`. The browser
  talks to LiveKit only through the `VoiceTransport` interface; Playwright swaps in a no-audio test
  transport (`NEXT_PUBLIC_VOICE_TEST_TRANSPORT=1`). Technical details stay collapsed; no raw JSON or
  analytics in the main view. A call list in Activity is not built (call details are reached from the
  Playground outcome).
- M4 (done, see `evaluations.md`): the Evaluations page polls a run once a second while it is queued or running, shows persisted results, and reruns one scenario as a linked run. Mode B and C appear as "Not run" with the reason.
- M5: populate `ActivityList` / `ActivityDetail` from stored calls and evaluation runs.
- Virtual-keyboard behaviour was not tested on a real device.
