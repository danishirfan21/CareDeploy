---
name: CareDeploy
colors:
  surface: '#fcf9f8'
  surface-dim: '#dcd9d9'
  surface-bright: '#fcf9f8'
  surface-container-lowest: '#ffffff'
  surface-container-low: '#f6f3f2'
  surface-container: '#f0eded'
  surface-container-high: '#eae7e7'
  surface-container-highest: '#e5e2e1'
  on-surface: '#1c1b1b'
  on-surface-variant: '#3e4947'
  inverse-surface: '#313030'
  inverse-on-surface: '#f3f0ef'
  outline: '#6e7977'
  outline-variant: '#bdc9c6'
  surface-tint: '#006a63'
  primary: '#005c55'
  on-primary: '#ffffff'
  primary-container: '#0f766e'
  on-primary-container: '#a3faef'
  inverse-primary: '#80d5cb'
  secondary: '#5d5e66'
  on-secondary: '#ffffff'
  secondary-container: '#e3e1ec'
  on-secondary-container: '#63646c'
  tertiary: '#7f4025'
  on-tertiary: '#ffffff'
  tertiary-container: '#9c573a'
  on-tertiary-container: '#ffe5db'
  error: '#ba1a1a'
  on-error: '#ffffff'
  error-container: '#ffdad6'
  on-error-container: '#93000a'
  primary-fixed: '#9cf2e8'
  primary-fixed-dim: '#80d5cb'
  on-primary-fixed: '#00201d'
  on-primary-fixed-variant: '#00504a'
  secondary-fixed: '#e3e1ec'
  secondary-fixed-dim: '#c6c5cf'
  on-secondary-fixed: '#1a1b22'
  on-secondary-fixed-variant: '#46464e'
  tertiary-fixed: '#ffdbce'
  tertiary-fixed-dim: '#ffb598'
  on-tertiary-fixed: '#370e00'
  on-tertiary-fixed-variant: '#72361b'
  background: '#fcf9f8'
  on-background: '#1c1b1b'
  surface-variant: '#e5e2e1'
typography:
  headline-xl:
    fontFamily: Geist
    fontSize: 36px
    fontWeight: '600'
    lineHeight: 44px
    letterSpacing: -0.03em
  headline-xl-mobile:
    fontFamily: Geist
    fontSize: 28px
    fontWeight: '600'
    lineHeight: 36px
    letterSpacing: -0.02em
  headline-lg:
    fontFamily: Geist
    fontSize: 24px
    fontWeight: '600'
    lineHeight: 32px
    letterSpacing: -0.02em
  headline-lg-mobile:
    fontFamily: Geist
    fontSize: 20px
    fontWeight: '600'
    lineHeight: 28px
    letterSpacing: -0.015em
  headline-sm:
    fontFamily: Geist
    fontSize: 18px
    fontWeight: '500'
    lineHeight: 26px
    letterSpacing: -0.01em
  body-lg:
    fontFamily: Geist
    fontSize: 16px
    fontWeight: '400'
    lineHeight: 26px
    letterSpacing: -0.005em
  body-md:
    fontFamily: Geist
    fontSize: 14px
    fontWeight: '400'
    lineHeight: 22px
    letterSpacing: 0em
  body-sm:
    fontFamily: Geist
    fontSize: 13px
    fontWeight: '400'
    lineHeight: 18px
    letterSpacing: 0em
  code-md:
    fontFamily: JetBrains Mono
    fontSize: 13px
    fontWeight: '400'
    lineHeight: 20px
    letterSpacing: -0.01em
  code-sm:
    fontFamily: JetBrains Mono
    fontSize: 12px
    fontWeight: '400'
    lineHeight: 18px
    letterSpacing: 0em
  label-md:
    fontFamily: Geist
    fontSize: 12px
    fontWeight: '500'
    lineHeight: 16px
    letterSpacing: 0.01em
  label-mono:
    fontFamily: JetBrains Mono
    fontSize: 11px
    fontWeight: '500'
    lineHeight: 14px
    letterSpacing: 0.04em
rounded:
  sm: 0.25rem
  DEFAULT: 0.5rem
  md: 0.75rem
  lg: 1rem
  xl: 1.5rem
  full: 9999px
spacing:
  gutter: 1rem
  gutter-desktop: 1.5rem
  margin: 1rem
  margin-tablet: 1.5rem
  margin-desktop: 2rem
  space-xs: 0.25rem
  space-sm: 0.5rem
  space-md: 0.75rem
  space-lg: 1.25rem
  space-xl: 2rem
  space-2xl: 3rem
---

## Brand & Style

This design system establishes an ultra-focused, calm conversational workspace tailored specifically for forward-deployed engineers navigating mission-critical deployments, code synthesis, and infrastructure orchestration. 

The aesthetic is grounded in contemporary **editorial minimalism** and utility-driven clarity, heavily inspired by modern AI research environments. It actively strips away the chaotic instrumentation of legacy DevOps suites—eliminating dense KPI cards, blinking system charts, and metric-dense dashboards in favor of a single, deeply intentional linear timeline.

Key brand attributes:
- **Calm Authority:** A serene, distraction-free environment that lowers cognitive fatigue during high-stakes troubleshooting and deployment workflows.
- **Unobtrusive Utility:** UI chrome steps completely into the background, prioritizing pure conversational markdown, code blocks, diffs, and context traces.
- **Craft & Precision:** Razor-thin structural dividers, balanced typographic scale, and deliberate spatial cadence signal rigorous engineering standards.

## Colors

The color architecture is built around an airy, warm monochromatic foundation punctuated by a single restrained jewel-toned teal for interactive momentum.

- **Primary (`#0f766e` / `#0d9488`):** Deep restrained teal. Reserved strictly for intentional state triggers: active primary action buttons, active prompt submissions, conversational branch tags, and current session indicators. It is never used for decorative tinting or ambient backgrounds.
- **Secondary (`#71717a` / `#6b7280`):** Soft, neutral zinc. Applied to secondary metadata, timestamps, input placeholders, keyboard shortcuts, and utility icons.
- **Neutral (`#171717` / `#0d0d0d`):** Carbon ink. Provides high-contrast, razor-sharp legibility for prompt inputs, body copy, and streaming token responses.
- **Surfaces:** Pure crisp white (`#ffffff`) for elevated active panels and prompt composers; warm off-white (`#faf9f6` canvas, `#f7f7f8` sidebar/thread history) for base application backdrops.
- **Borders & Dividers:** Whisper-thin edges (`#ebebeb` to `#e5e5e7`) create discrete spatial separation without optical friction.

## Typography

Typography in this design system balances human editorial fluency with technical rigor. 

- **Primary System (`Geist`):** Delivers clean geometry, exceptional neutral legibility across long-form responses, and subtle tracking adjustments for a modern, focused look. Body line-heights are intentionally generous (`26px` on `16px` text) to facilitate rapid reading of technical step-by-step diagnostic plans.
- **Monospace Stack (`JetBrains Mono`):** Deployed for CLI outputs, deployment logs, system payload snippets, and status flags. It grounds the clean editorial body in absolute engineering precision.
- **Hierarchy Rules:** Never use heavy weights (`700`+) within the conversational workspace. Semibold (`600`) is reserved for main thread titles and section breakouts; regular (`400`) and medium (`500`) carry all conversational content to avoid visual heaviness.

## Layout & Spacing

The layout is centered around an unobstructed conversational spine rather than a multi-panel dashboard.

- **Conversation Spine:** The primary stream conforms strictly to a centered column: `max-w-2xl` (672px) for focused dialogue or `max-w-3xl` (768px) when inline diffs, stack traces, and terminal captures are active. This preserves optimal line length and prevents horizontal eye fatigue.
- **Sidebar Architecture:** A single collapsible left rail (`260px` fixed width) housing project threads and environment contexts. It collapses to a slim icon dock or hides entirely on mobile/tablet viewports.
- **Canvas Behavior:**
  - **Desktop (>= 1024px):** Centered conversation column with fluid lateral space. Bottom-docked floating prompt composer with fluid max-width matching the stream.
  - **Tablet (768px - 1023px):** Off-canvas navigation tray with sheet transitions. 24px outer margin.
  - **Mobile (< 768px):** Edge-to-edge flow with 16px lateral padding and compact top app bar. Floating action elements pin to the viewport bottom with safe area insets.

## Elevation & Depth

This system avoids decorative, multi-layered, or high-blur drop shadows. Depth is achieved strictly through **tonal transitions** and **hairline demarcation**:

- **Ground (Level 0):** `#faf9f6` canvas surface. The tranquil base for the central conversation.
- **Recessed / Utility (Level 0.5):** `#f7f7f8` sidebar and secondary context drawers. Separated from the base solely via a 1px solid border (`#ebebeb`).
- **Surface (Level 1):** `#ffffff` applied to user query bubbles, code block containers, popovers, and the bottom floating prompt input.
- **Elevation Accent:** For modal dialogs and the floating prompt composer, an imperceptible ambient grounding shadow is permitted: `0 2px 8px -2px rgba(0, 0, 0, 0.04), 0 1px 3px -1px rgba(0, 0, 0, 0.02)`. 
- **Borders over Shadows:** Element boundaries are defined by a crisp 1px stroke (`#e5e5e7`). When active or focused, interactive elements transition to a subtle `#0f766e` stroke without bloom or glow effects.

## Shapes

The shape vocabulary introduces softness to an otherwise disciplined, technical workspace. 

- **Containers & Prompt Bar:** Standard containers, dialogs, and conversational cards use `rounded-xl` (1rem / 16px) or `rounded-2xl` (1.5rem / 24px) to balance technical precision with approachable, organic softness.
- **Interactive Controls:** Buttons, chips, and input pills adopt either `rounded-lg` (0.5rem / 8px) for compact utility toggles or full pills (`rounded-full`) for context badges and filter tokens.
- **Code & Terminals:** Code blocks maintain `rounded-xl` with cleanly clipped overflow headers for copy/branch operations.

## Components

### Conversational Feed & Message Turns
- **User Message:** Minimalist, soft white card (`#ffffff`) aligned to the right or subtly offset, wrapped in a 1px `#e5e5e7` border with `rounded-2xl` padding (`space-lg`).
- **Assistant Response:** Seamlessly anchored directly onto the base background (`#faf9f6`), without card wrappers, maximizing whitespace and editorial rhythm. Stream text renders in `body-lg` neutral `#171717`.

### Prompt Composer
- Centered dock floating at the viewport bottom, matching the conversational column width (`max-w-2xl` or `max-w-3xl`).
- Background `#ffffff`, bordered by `1px solid #e5e5e7`, `rounded-2xl`, with ambient depth.
- Contains auto-expanding textarea, secondary action cluster (context attachments, environment selector) aligned bottom-left in `#71717a`, and submit button bottom-right.
- Submit button: Crisp circular pill (`rounded-full`), `#0f766e` fill with white arrow when active; neutral `#f4f4f5` with muted icon when input is empty.

### Buttons & Interactive Badges
- **Primary Button:** `#0f766e` background, pure white text, `rounded-lg`, smooth hover transition to `#0d9488`. Zero shadow.
- **Secondary Button:** Pure white background, `1px solid #e5e5e7`, `#171717` label. Hover renders `#f7f7f8`.
- **Ghost Action:** Flat `#71717a` text/icon, hover creates soft `#f4f4f5` background with zero border.
- **Context Chips:** `rounded-full`, `1px solid #ebebeb`, `#ffffff` surface, pairing `JetBrains Mono` label text with a tiny green/teal status indicator dot.

### Code Blocks & Log Diffs
- Light slate code container (`#f7f7f8`) bounded by a 1px `#e5e5e7` border with `rounded-xl`.
- Subtle top status bar displaying the file path, runtime language tag (`JetBrains Mono`), and a ghost "Copy" action.
- Diffs use faint green (`#0f766e10`) and soft red (`#ef444410`) backgrounds with clear +/- gutters.

### Input Fields & Controls
- Form inputs feature warm white backgrounds, 1px `#e5e5e7` perimeter, and smooth 150ms transitions to `#0f766e` border focus states with zero outline rings.
- Checkboxes and radios utilize `#0f766e` fills with minimal scale transitions when checked.