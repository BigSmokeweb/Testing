# AutoQA Frontend Design System & Styling Guide

This document provides a comprehensive reference for the frontend design system of AutoQA, detailing design tokens, color palettes, typography, components, animations, and responsive layouts defined in `app/static/style.css`.

---

## 1. Design Overview & Principles

AutoQA's user interface is designed as an enterprise-grade QA dashboard. It follows a dark-mode-first aesthetic with slate/zinc neutral tones, high contrast typography, and purposeful semantic accents.

### Core Principles
- **Dark Elegance**: Deep background surfaces (`#0b0f19`, `#111827`) paired with subtle borders (`#1f2937`, `#374151`).
- **Semantic Clarity**: Distinct, recognizable color coding for test execution statuses (Passed, Failed, Running, Queued).
- **High Readability**: System and modern sans-serif typography with strict hierarchy and monospaced code blocks.
- **Micro-Interactions**: Smooth 150ms-200ms transitions on interactive states, cards, buttons, and badges.

---

## 2. Typography & Fonts

### Font Families
- **Primary Body Font**:
  `-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Oxygen, Ubuntu, Cantarell, "Open Sans", "Helvetica Neue", sans-serif`
- **Monospace Code Font**:
  `ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace`

### Type Scale & Hierarchy
| Element | Font Size | Line Height | Font Weight | Letter Spacing | Color Token |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **H1** | `2rem` (32px) | `1.2` | `700` | `-0.025em` | `--text-primary` (`#f9fafb`) |
| **H2** | `1.5rem` (24px) | `1.25` | `600` | `-0.02em` | `--text-primary` (`#f9fafb`) |
| **H3** | `1.25rem` (20px) | `1.3` | `600` | `-0.01em` | `--text-primary` (`#f9fafb`) |
| **H4** | `1.125rem` (18px) | `1.35` | `600` | normal | `--text-primary` (`#f9fafb`) |
| **Body (Default)** | `0.9375rem` (15px) | `1.5` | `400` | normal | `--text-secondary` (`#9ca3af`) |
| **Small / Captions** | `0.8125rem` (13px) | `1.4` | `400` / `500` | normal | `--text-muted` (`#6b7280`) |
| **Tiny / Badges** | `0.75rem` (12px) | `1.2` | `600` | `0.025em` | contextual |

---

## 3. Color Palette & Design Tokens

### Background Surfaces
| Variable | Value | Description & Purpose |
| :--- | :--- | :--- |
| `--bg-base` | `#0b0f19` | Deep root canvas background |
| `--bg-surface` | `#111827` | Primary card, container, and navbar background |
| `--bg-surface-raised`| `#1a2234` | Lifted cards, dialogs, dropdown menus, table headers |
| `--bg-hover` | `#1f293d` | Hover state for interactive rows, cards, and list items |
| `--bg-active` | `#253046` | Active / pressed background state |

### Borders & Dividers
| Variable | Value | Description & Purpose |
| :--- | :--- | :--- |
| `--border-subtle` | `#1f2937` | Subtle separators, table row divides |
| `--border-default` | `#374151` | Standard card borders and input field outlines |
| `--border-focus` | `#60a5fa` | Focus ring outline color for form controls |

### Text Colors
| Variable | Value | Description & Purpose |
| :--- | :--- | :--- |
| `--text-primary` | `#f9fafb` | Main headings, primary content, table values |
| `--text-secondary` | `#9ca3af` | Secondary labels, descriptions, subheadings |
| `--text-muted` | `#6b7280` | Timestamps, placeholders, hints, inactive badges |
| `--text-inverse` | `#0b0f19` | High-contrast dark text over bright background buttons |

### Brand & Accent
| Variable | Value | Description & Purpose |
| :--- | :--- | :--- |
| `--brand-primary` | `#3b82f6` | Royal blue primary button, focus accents, primary links |
| `--brand-hover` | `#2563eb` | Primary brand interactive hover color |
| `--brand-glow` | `rgba(59, 130, 246, 0.25)` | Subtle glowing drop shadow on primary active components |

### Semantic & Status Colors
| Status | Background Token | Value | Text Token | Value | Usage |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Success (Pass)** | `--status-pass-bg` | `rgba(16, 185, 129, 0.12)` | `--status-pass-text` | `#34d399` | Passed test cases, active healthy sites |
| **Error (Fail)** | `--status-fail-bg` | `rgba(239, 68, 68, 0.12)` | `--status-fail-text` | `#f87171` | Failed test runs, errors, destructive alerts |
| **Warning** | `--status-warn-bg` | `rgba(245, 158, 11, 0.12)` | `--status-warn-text` | `#fbbf24` | Warnings, flakiness, caution alerts |
| **Info / Running** | `--status-info-bg` | `rgba(59, 130, 246, 0.12)` | `--status-info-text` | `#60a5fa` | In-progress test executions, info banners |
| **Queued / Neutral**| `--status-queued-bg`| `rgba(107, 114, 128, 0.15)`| `--status-queued-text`| `#9ca3af` | Pending jobs, idle state |

---

## 4. Spacing Scale & Elevation

### Spacing Scale
- `--space-xs`: `0.25rem` (4px) - Tight badge padding, inline icon gaps
- `--space-sm`: `0.5rem` (8px) - Small button padding, form input vertical padding
- `--space-md`: `0.75rem` (12px) - Standard element margins, badge padding
- `--space-lg`: `1rem` (16px) - Standard card padding, button horizontal padding
- `--space-xl`: `1.5rem` (24px) - Section padding, modal padding, large card bodies
- `--space-2xl`: `2rem` (32px) - Page container margins, hero spacing
- `--space-3xl`: `3rem` (48px) - Landing page section padding

### Border Radii
- `--radius-sm`: `4px` (Small badges, tags, code chips)
- `--radius-md`: `6px` (Buttons, form inputs, small boxes)
- `--radius-lg`: `8px` (Standard dashboard cards, dialogs, tables)
- `--radius-xl`: `12px` (Hero cards, modals, container blocks)
- `--radius-full`: `9999px` (Pills, circular progress indicators, avatars)

### Elevation & Shadows
- **Card Shadow (`--shadow-sm`)**: `0 1px 3px rgba(0, 0, 0, 0.3)`
- **Raised Surface Shadow (`--shadow-md`)**: `0 4px 6px -1px rgba(0, 0, 0, 0.4), 0 2px 4px -2px rgba(0, 0, 0, 0.3)`
- **Modal / Dropdown Shadow (`--shadow-lg`)**: `0 10px 15px -3px rgba(0, 0, 0, 0.5), 0 4px 6px -4px rgba(0, 0, 0, 0.4)`
- **Focus Ring**: `0 0 0 3px rgba(59, 130, 246, 0.35)`

---

## 5. Components & UI Elements

### 5.1 Buttons
- **Primary Button (`.btn-primary`)**:
  - Background: `--brand-primary` (`#3b82f6`), Text: `#ffffff`
  - Hover: Background `--brand-hover` (`#2563eb`), Box shadow glow
- **Secondary Button (`.btn-secondary`)**:
  - Background: `--bg-surface-raised`, Border: `1px solid --border-default`, Text: `--text-primary`
  - Hover: Background `--bg-hover`, Border: `--text-muted`
- **Danger Button (`.btn-danger`)**:
  - Background: `rgba(239, 68, 68, 0.15)`, Border: `1px solid rgba(239, 68, 68, 0.3)`, Text: `#f87171`
  - Hover: Background `rgba(239, 68, 68, 0.25)`, Border: `#ef4444`

### 5.2 Forms & Inputs
- Inputs (`input[type="text"]`, `input[type="url"]`, `select`, `textarea`):
  - Background: `#0e1422` with border `--border-default` (`#374151`)
  - Text: `--text-primary` (`#f9fafb`)
  - Focus: Border `--brand-primary`, box-shadow ring
  - Disabled: Opacity 0.6, cursor not-allowed

### 5.3 Badges & Status Pills
- **Base Style (`.badge`)**: Inline flex, `padding: 2px 8px`, border radius `--radius-full`, font size `0.75rem`, font weight `600`.
- Variants:
  - `.badge-pass`: Green background (`--status-pass-bg`) & text (`--status-pass-text`)
  - `.badge-fail`: Red background (`--status-fail-bg`) & text (`--status-fail-text`)
  - `.badge-running`: Blue background (`--status-info-bg`) & text (`--status-info-text`), with pulse animation
  - `.badge-queued`: Gray background (`--status-queued-bg`) & muted text

### 5.4 Tables
- Tables feature sticky-friendly headers (`thead th`) with `--bg-surface-raised` background, subtle uppercase typography, and divider borders.
- Rows have hover effects with `--bg-hover` for fast scannability.
- Cells have responsive text trimming and wrap rules.

### 5.5 Error Screenshots & Modal Previews
- Thumbnail cards with border `--border-default`, smooth hover scale transition.
- Fullscreen modal overlay (`background: rgba(0, 0, 0, 0.85)`) with backdrop blur for inspecting captured regression screenshots.

---

## 6. Responsiveness & Breakpoints

AutoQA supports mobile, tablet, and desktop viewing:

### Desktop (> 1024px)
- Multi-column dashboard grids, side-by-side run detail views, wide tabular metrics.

### Tablet (768px - 1024px)
- Fluid container widths (`max-width: 100%`), 2-column KPI grids, responsive navigation toggle.

### Mobile (< 768px)
- Single column stacked layout.
- Horizontal scroll wrappers for data-heavy audit tables (`.table-responsive`).
- Form actions stack vertically to ensure full-width touch targets (minimum 44px height).
- Breadcrumb trimmings and optimized modal viewports.

---

## 7. Accessibility & Motion

- **Focus Management**: All interactive elements (`a`, `button`, `input`) have visible, high-contrast outline focus rings for keyboard navigation.
- **Screen Reader Support**: Utility class `.sr-only` keeps assistive text accessible without disrupting visual layouts.
- **Reduced Motion**: Full support for `@media (prefers-reduced-motion: reduce)` to disable non-essential animations and transitions.

---

## 8. Quick Color Reference Card

| Token Name | Hex / RGBA | Role |
| :--- | :--- | :--- |
| Canvas Background | `#0b0f19` | App Canvas |
| Surface Background | `#111827` | Cards & Containers |
| Raised Surface | `#1a2234` | Headers & Popovers |
| Surface Hover | `#1f293d` | Interaction States |
| Border Default | `#374151` | Component Outlines |
| Text Primary | `#f9fafb` | High Contrast Headings |
| Text Secondary | `#9ca3af` | Readable Content |
| Text Muted | `#6b7280` | Micro-labels |
| Brand Primary | `#3b82f6` | Action Accent |
| Pass Accent | `#34d399` | Success State |
| Fail Accent | `#f87171` | Error State |
| Warn Accent | `#fbbf24` | Alert State |
