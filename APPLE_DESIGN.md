# APPLE_DESIGN.md: Apple-Style Redesign for AutoQA

Put this file in the project root next to `DESIGN_SYSTEM.md`. When asked to "apply APPLE_DESIGN.md", follow it exactly.

This is a visual redesign inspired by Apple's Human Interface Guidelines (clarity, deference, depth). It does not copy any Apple logo, icon, image, or proprietary asset, and it never claims to be an Apple product.

---

## 0. Rules for the agent

1. **Visual change only.** Do not change routes, form fields, names/ids used by tests, CSRF tokens, security behaviour, database, or Python logic. If a template change needs a Python change, stop and ask using the DECISION NEEDED format.
2. Only edit: `app/static/style.css`, `app/templates/*.html`, and one optional `app/static/app.js` (theme toggle and small UI helpers). Nothing else.
3. No external CDNs, fonts, or icon packs. Use the system font stack and inline SVG icons.
4. Keep every existing CSS class name working (`.btn-primary`, `.badge-pass`, and so on). Add new tokens and classes; do not remove old ones until all templates are migrated.
5. Run the full test suite after each stage. Tests must still pass (74 at last count).
6. Commit per stage. Do not push.
7. Light and dark themes must both work. Default follows the user's system (`prefers-color-scheme`), with a manual toggle remembered in `localStorage` (wrapped in try/catch).
8. Never rely on color alone for status. Every status shows an icon or text too.

---

## 1. Design principles

- **Clarity:** content first, generous whitespace, one primary action per screen.
- **Deference:** the interface stays quiet; color is used for meaning (status, primary action), not decoration.
- **Depth:** subtle translucency, soft layered surfaces, and gentle motion show hierarchy. No heavy borders or hard shadows.
- **Consistency:** the same radius, spacing, and type scale everywhere.

---

## 2. Design tokens (replace the `:root` token block)

Define on `:root` for light, override under `@media (prefers-color-scheme: dark)` with `:root:not([data-theme="light"])`, and again under `:root[data-theme="dark"]`.

### 2.1 Color: light

| Token | Value | Use |
|---|---|---|
| `--bg` | `#F2F2F7` | page background |
| `--bg-elevated` | `#FFFFFF` | cards, tables |
| `--bg-secondary` | `#F9F9FB` | table header, input fill |
| `--bg-hover` | `rgba(0,0,0,0.04)` | row/card hover |
| `--label` | `#000000` | primary text |
| `--label-secondary` | `rgba(60,60,67,0.60)` | secondary text |
| `--label-tertiary` | `rgba(60,60,67,0.30)` | placeholders (not for essential text) |
| `--separator` | `rgba(60,60,67,0.18)` | hairlines |
| `--blue` | `#007AFF` | primary action, links, focus |
| `--green` | `#34C759` | passed |
| `--red` | `#FF3B30` | failed, destructive |
| `--orange` | `#FF9500` | warning, flaky |
| `--gray` | `#8E8E93` | queued, neutral |

### 2.2 Color: dark

| Token | Value |
|---|---|
| `--bg` | `#000000` |
| `--bg-elevated` | `#1C1C1E` |
| `--bg-secondary` | `#2C2C2E` |
| `--bg-hover` | `rgba(255,255,255,0.06)` |
| `--label` | `#FFFFFF` |
| `--label-secondary` | `rgba(235,235,245,0.60)` |
| `--label-tertiary` | `rgba(235,235,245,0.30)` |
| `--separator` | `rgba(84,84,88,0.65)` |
| `--blue` | `#0A84FF` |
| `--green` | `#30D158` |
| `--red` | `#FF453A` |
| `--orange` | `#FF9F0A` |
| `--gray` | `#98989D` |

### 2.3 Tinted status fills (both themes)
`--green-tint: color-mix(in srgb, var(--green) 15%, transparent)`, and the same for red, orange, blue, gray. Badge text uses the solid color. Verify text contrast (see section 9); if a solid color on its tint is below 4.5:1, darken the text in light mode (for example green text `#1E7B34`, orange text `#9A5B00`).

### 2.4 Spacing (8-point grid)
`--s1: 4px; --s2: 8px; --s3: 12px; --s4: 16px; --s5: 24px; --s6: 32px; --s7: 48px; --s8: 64px;`
Content max width `1080px` (reading pages `720px`). Side gutter 16px on mobile, 24px on desktop.

### 2.5 Radius
`--r-sm: 8px; --r-md: 12px; --r-lg: 16px; --r-xl: 22px; --r-pill: 999px;`
Cards use `--r-lg`. Buttons and inputs use `--r-md` (primary buttons on the landing hero may use pill).

### 2.6 Elevation
Prefer separation by surface color and hairlines, not shadows.
- `--shadow-card: 0 1px 2px rgba(0,0,0,0.04), 0 4px 16px rgba(0,0,0,0.06)` (light only; dark uses none)
- `--shadow-pop: 0 8px 30px rgba(0,0,0,0.18)` for menus and modals

### 2.7 Material (translucent bars)
```css
.bar {
  background: color-mix(in srgb, var(--bg-elevated) 72%, transparent);
  -webkit-backdrop-filter: saturate(180%) blur(20px);
  backdrop-filter: saturate(180%) blur(20px);
  border-bottom: 0.5px solid var(--separator);
}
```
Provide a solid fallback for browsers without `backdrop-filter` (`@supports not (...)`).

Material rules (from the skill):
- Material weight encodes hierarchy. Never stack a light translucent surface on another translucent surface.
- Bigger surfaces read thicker: stronger blur and deeper shadow for sheets than for the navbar.
- Dim to focus (modal: scrim + push the background back). Separate to keep flow (side panel: translucency, no scrim).
- Over translucent surfaces use slightly heavier, higher-contrast text with a small letter-spacing bump; put color on a solid layer.
- Prefer a scroll-edge fade (mask) under the navbar instead of a 1px hard divider.

---

## 3. Typography

Font stack (system fonts, so it renders in SF Pro on Apple devices and a native sans elsewhere; do not bundle Apple fonts):
```css
--font: -apple-system, BlinkMacSystemFont, "SF Pro Text", "SF Pro Display",
        "Segoe UI Variable", "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
--font-mono: ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, monospace;
```

| Style | Size / line | Weight | Tracking | Use |
|---|---|---|---|---|
| Large Title | 34 / 41 | 700 | -0.02em | landing hero (mobile 30) |
| Title 1 | 28 / 34 | 700 | -0.02em | page titles |
| Title 2 | 22 / 28 | 600 | -0.015em | section titles |
| Title 3 | 20 / 25 | 600 | -0.01em | card titles |
| Headline | 17 / 22 | 600 | 0 | table heads, labels |
| Body | 17 / 24 | 400 | 0 | default (16px minimum on mobile) |
| Callout | 16 / 21 | 400 | 0 | helper text |
| Subhead | 15 / 20 | 400 | 0 | secondary info |
| Footnote | 13 / 18 | 400 | 0 | timestamps, hints |
| Caption | 12 / 16 | 500 | 0.01em | badges, tiny labels |

Tracking is size-specific: tighten large display text (about -0.02em), body near 0, small text slightly positive. Leading shrinks as size grows (display ~1.05 to 1.1, body 1.5). Respect the user's text-size setting: size and space in `rem`. Rules: use weights 400/500/600/700 only. Titles use `text-wrap: balance`. Body text lines max 70 characters. Numbers in tables use `font-variant-numeric: tabular-nums`.

---

## 4. Layout

- **Navbar:** sticky, 52px, translucent material (section 2.7). Left: product name (Headline). Center/right: nav links (Subhead, `--label-secondary`, active = `--label`). Far right: theme toggle and account menu. On mobile collapse to a menu button.
- **Page header:** Title 1 + one-line Callout description + the single primary action aligned right (stacked on mobile).
- **Content:** cards stacked with `--s5` gap. Group related rows inside one card with hairline separators (inset list style) instead of many small boxes.
- **Whitespace:** at least `--s6` above major sections, `--s7` on the landing page.

---

## 5. Components

### 5.1 Buttons
- Height 44px (touch target), padding `0 20px`, radius `--r-md`, Headline weight 500/600, no uppercase.
- **Primary:** fill `--blue`, white text. Hover: 8% darker. Active: scale 0.98 and 12% darker.
- **Secondary:** fill `--bg-secondary`, text `--blue`.
- **Tertiary/text:** no fill, text `--blue`.
- **Destructive:** fill `--red-tint`, text `--red` (a solid red fill only inside a confirmation dialog).
- Disabled: 40% opacity, `cursor: not-allowed`. Loading: inline spinner replaces the label, width stays fixed.
- Only **one** primary button per view.

### 5.2 Forms
- Inputs 44px high, fill `--bg-secondary`, no border by default, radius `--r-md`, 16px font (prevents zoom on iOS).
- Focus: 4px ring `color-mix(in srgb, var(--blue) 35%, transparent)` plus `--blue` outline offset 0. Never remove focus indication.
- Labels above fields (Subhead, `--label-secondary`). Helper text under (Footnote). Errors under in `--red` with an icon, and `aria-describedby` linking field to message.
- Checkbox/toggle: 22px, accent `--blue`.
- Group fields of one task inside a single inset card with hairlines.

### 5.3 Cards
`--bg-elevated`, radius `--r-lg`, padding `--s5`, `--shadow-card` in light, 0.5px `--separator` border in dark. Interactive cards lift 1px and show `--bg-hover` on hover (150 to 200ms).

### 5.4 Status badges
Pill, Caption weight 600, height 24px, padding `0 10px`, tinted fill + solid text + a 12px inline SVG icon:
- Passed: check-circle, green. Failed: x-circle, red. Flaky/Warning: exclamation-triangle, orange.
- Running: spinner (rotating) or pulsing dot, blue. Queued: clock, gray. Expired/blocked: lock or shield, orange.
Keep existing class names (`.badge-pass`, `.badge-fail`, `.badge-running`, `.badge-queued`) and map any other status class in use to these.

### 5.5 Tables
- Header: `--bg-secondary`, Footnote 600, `--label-secondary`, no uppercase, no heavy borders.
- Rows: 52px minimum, hairline separators only, hover `--bg-hover`.
- Numeric columns right-aligned with tabular numbers.
- On mobile (<768px) wrap in `.table-responsive` (horizontal scroll) or convert rows to stacked cards for History and Sites.

### 5.6 Progress and score
- Run progress: linear bar 6px high, radius pill, track `--bg-secondary`, fill `--blue`, animated indeterminate while queued. 
- Score: large ring or number (Large Title) with a color word label ("Good", "Needs attention"), never color alone.

### 5.7 Alerts and banners
Inset card with a 4px left accent in the semantic color, an icon, a Headline title and Callout body. Use for `run.note`, "Connection lost, retry", session/verification notices, and flash messages.

### 5.8 Screenshots and modals
Thumbnails: radius `--r-md`, 0.5px separator border, hover scale 1.02. Modal: dimmed `rgba(0,0,0,0.5)` + blur scrim, content `--r-xl`, `--shadow-pop`, closes on Esc and outside click, traps focus, restores focus on close.

### 5.9 Empty and error states
Centered icon (48px, `--label-tertiary`), Title 3, one Callout sentence, one primary action. Apply to "no sites", "no runs", 404, 500, terms/privacy placeholders.

---

## 6. Motion and interaction (from the apple-design skill)

Motion is behaviour, not decoration. An interface feels alive when it responds instantly, tracks the pointer 1:1, carries momentum, and can be interrupted at any moment.

### 6.1 Rules
1. **Respond on pointer-down, not release.** Buttons highlight and scale (0.97, 100ms ease-out) the instant they are pressed. Remove artificial delays, debounces and waits that add latency.
2. **Never lock input during a transition.** Every animation must be interruptible and redirectable. Always animate from the current on-screen value, never from the target value.
3. **Use springs for anything gesture-driven** (sheets, drawers, modals, drag, swipe). Avoid CSS `transition`/`@keyframes` for those; CSS transitions are fine for hover, color and opacity changes.
4. **Direct manipulation is 1:1.** While dragging, the element stays glued to the pointer and respects the grab offset. Use Pointer Events with `setPointerCapture`, and keep the last few positions with timestamps to compute release velocity.
5. **Hand off velocity.** On release, the spring continues at the pointer's velocity. Project the resting point: `current + (v/1000) * d / (1 - d)` with `d = 0.998`, then snap to the nearest target. Use velocity sign to decide between reverse and commit.
6. **Rubber-band at edges** with progressive resistance instead of a hard stop: `(overshoot * dim * 0.55) / (dim + 0.55 * |overshoot|)`.
7. **Spatial consistency:** enter and exit along the same path, set `transform-origin` to the trigger, mirror easing on reversible transitions.
8. Animate only `transform` and `opacity` (plus color). Use `requestAnimationFrame`, and `will-change` only where motion is imminent.

### 6.2 Spring defaults
| Interaction | Damping | Response |
|---|---|---|
| Default UI (move, expand, toggle) | 1.0 (no bounce) | 0.3 to 0.4 s |
| Rotation | 0.8 | 0.4 s |
| Drawer / sheet / flick release | 0.8 (slight bounce, only because a flick carried momentum) | 0.3 s |

Use a spring library that retargets from current velocity (Motion / Framer Motion, no CDN: bundle locally or write a small spring in `app.js`):
```js
animate(el, { y: 0 }, { type: 'spring', bounce: 0, duration: 0.4 });
```
Decompose 2D motion into independent X and Y springs. Materialize overlays by animating blur and scale together, not just opacity.

### 6.3 Where to apply it in AutoQA
- Buttons and rows: instant press feedback.
- Screenshot modal: opens from the clicked thumbnail (origin anchored), closes by dragging down with velocity handoff, interruptible mid-open.
- Report failure cards: expand/collapse with a no-bounce spring, can be reversed mid-animation.
- Mobile nav menu and any bottom sheet: spring sheet with rubber-banding.
- Progress page: smooth bar and counter updates, never blocking input.
- Do not add motion that delays finishing a task.

### 6.4 Motion acceptance
- Interrupt every animation mid-way (click again, drag back): it must redirect without a jump.
- No input is ever ignored during a transition.
- Per-frame movement stays smooth at 60fps (check in the browser performance panel).

### 6.5 Reduced motion, transparency and contrast
```css
@media (prefers-reduced-motion: reduce) {
  .sheet, .modal, .card { transition: opacity 200ms ease; transform: none !important; }
  /* replace slides and springs with short cross-fades; no overshoot; spinners become a static "Running" label */
}
@media (prefers-reduced-transparency: reduce) {
  .bar { background: var(--bg-elevated); backdrop-filter: none; }
}
@media (prefers-contrast: more) {
  :root { --separator: currentColor; }
  .card { border: 1px solid var(--label); }
}
```
Avoid full-viewport moving backgrounds, slow looping oscillations, and abrupt brightness jumps.

---

## 7. Responsive

| Width | Behaviour |
|---|---|
| < 600px | single column, 16px gutters, full-width buttons, stacked forms, nav in a menu |
| 600 to 1024px | 2-column KPI grids, container fluid |
| > 1024px | content max 1080px centered, side-by-side summary + details on the report |

Respect safe areas: `padding-left: max(16px, env(safe-area-inset-left))` and the same for right/bottom. Minimum touch target 44x44px. No horizontal page scroll at 320px.

---

## 8. Page-by-page spec

1. **Landing (`index`):** hero with Large Title ("Test your website in minutes" or the existing copy), one-line Callout, a large URL input with an inline primary button, and a quiet "What we test" 2x3 grid of icon + short text. Three-step "How it works" row. Footer with Terms and Privacy. Trust note: "Only sites you own."
2. **Auth (`login`, `register`):** centered 400px card, Title 2, fields, one primary button, text link to the other page. Generic error message styling (alert banner).
3. **Sites:** inset list; each row shows domain, verified badge, last run status, and a Run button. Add-site form in a card at top. Empty state when none.
4. **Wizard:** 3 steps with a stepper (numbered circles, completed = check), one card per step, primary "Continue" bottom right. Authorization checkbox clearly labelled and required. Copy buttons for the verification token (with "Copied" feedback).
5. **Progress:** large centered status with icon and elapsed time, progress bar, pages checked counter (tabular numbers), note banner for failures, "Connection lost, retry" banner.
6. **Report:** header with domain, date, status badge; summary row of 4 stat cards (Score, Pages, Errors, Avg load); failures first as expandable cards (screenshot thumbnail, error, page URL, "Copy issue text" tertiary button); passed pages in a collapsed list; link-check table; previous-run comparison banner. Print stylesheet: white background, no nav, no shadows.
7. **History:** table with status badge, date, engine, pass/fail counts, "View report" text link. Pagination or "Load more" if long.
8. **Terms/Privacy:** reading layout (720px), Title 1, Body text, clear note if placeholder.
9. **404/500:** empty-state pattern with a "Back to home" action.

---

## 9. Accessibility acceptance

- Text contrast at least 4.5:1 (3:1 for 17px+ semibold and UI icons) in BOTH themes. Check badges, secondary text, placeholders, disabled states.
- Visible focus on every interactive element, logical tab order, skip-to-content link.
- Headings in order (one `h1` per page). Landmarks: `header`, `nav`, `main`, `footer`.
- Form fields have labels; errors are announced (`role="alert"` for flash/errors, `aria-live="polite"` for progress updates).
- Status never conveyed by color alone.
- Works at 200% zoom and 320px width, with keyboard only, and with reduced motion.
- Theme toggle has an accessible name and reflects state (`aria-pressed`).

---

## 10. Implementation stages (commit after each, run tests each time)

1. **Tokens:** add the token block, light/dark switching, font stack, base typography. Keep old variable names as aliases pointing to the new tokens so nothing breaks.
2. **Base components:** buttons, forms, cards, badges, tables, alerts in `style.css`.
3. **Shell:** `base.html` navbar (material), footer, theme toggle (`app.js`), skip link.
4. **Pages in this order:** landing, auth, sites, wizard, progress, report, history, terms/privacy, 404/500.
5. **Motion and polish:** transitions, reduced-motion, loading states, empty states, print CSS.
6. **QA:** run section 11.

---

## 11. Final QA checklist (report results honestly, say "not checked" where you did not)

- [ ] Full pytest suite passes (before and after)
- [ ] No Python files changed (`git diff --stat` shows only CSS, templates, one JS file)
- [ ] Every page checked in light and dark at 360px, 768px, 1280px
- [ ] No horizontal scroll at 320px
- [ ] Keyboard-only walkthrough of the wizard and a report
- [ ] Contrast checked for badges and secondary text in both themes
- [ ] Reduced motion honoured
- [ ] No external requests (fonts, CDNs, icons) in the network tab
- [ ] Theme toggle works and `localStorage` failure does not break the page
- [ ] Screenshots of each page attached to the final message (or a clear note that they could not be taken)

## 12. Design foundations to check each screen against
1. **Purpose:** one clear job per screen; leave out what is not needed.
2. **Agency:** the user stays in control; easy undo; confirmation only for destructive actions (delete account, delete site).
3. **Responsibility:** privacy and safety at the right moment (credentials note, "only sites you own").
4. **Familiarity:** standard patterns first; break one only if it is clearly better.
5. **Flexibility:** works across devices, text sizes, input methods and abilities.
6. **Simplicity (not minimalism):** common path first, advanced options one level deeper; direct, specific labels ("Run test", not "Submit").
7. **Craft:** every spacing, timing and alignment value comes from the tokens.
8. **Delight:** the result of the other seven; calm, confident, fast.
Also: validate forms inline (not only on submit), always show wayfinding (where am I, where can I go, how do I get out), and group related controls by proximity.

## 13. Out of scope
New features, new pages, copy rewrites beyond small label fixes, animations that delay task completion, Apple logos or imagery, bundled Apple fonts.
