# Worldsim — Design notes

White and black only. Signal is carried by shade, fill, and shape, never by hue.

## Tokens (`apps/web/src/app/globals.css`)

| Token | Light | Dark | Note |
|---|---|---|---|
| `--bg` | `#FFFFFF` | `#000000` | page and map land |
| `--surface` | `#F7F7F7` | `#0A0A0A` | cards, panels |
| `--ink` | `#0A0A0A` | `#FFFFFF` | primary text, solid dots |
| `--muted` | `#6B6B6B` | `#8F8F8F` | secondary text; dark uses `#8F8F8F` (6.2:1) because `#6B6B6B` on black is 3.9:1 |
| `--line` | `#E5E5E5` | `#1F1F1F` | 1px hairlines |
| `--gray-2` | `#BFBFBF` | `#4A4A4A` | "aware" fill, disabled |

Spacing on an 8px grid. Radius 12px on cards, 999px on pills. Hairline borders only; no shadows except a 1px ring on floating cards.

Type: Geist Sans for UI, Geist Mono with `tabular-nums` for every number and date. Scale 11 / 12 / 13 / 15 / 20 px.

Motion: 150–250 ms ease-out. Active dots pulse softly; flows animate a dash offset. `prefers-reduced-motion` disables both.

## Map palette

| Layer | Light | Dark |
|---|---|---|
| land (background) | `#FFFFFF` | `#000000` |
| water | `#EFEFEF` | `#0F0F0F` |
| admin-0 boundary | `#CFCFCF` | `#333333` |
| admin-1 boundary (dashed, z ≥ 4) | `#E5E5E5` | `#1F1F1F` |
| roads (z ≥ 6 major, z ≥ 11 all) | `#E5E5E5` / `#D9D9D9` | `#1F1F1F` / `#2A2A2A` |
| buildings (z ≥ 13) | `#F0F0F0` | `#0A0A0A` |
| labels / halo | `#6B6B6B` / `#FFFFFF` | `#8F8F8F` / `#000000` |

## Status encoding

People are circles, institutions are squares, so the distinction survives in black and white.

| Status | Mark |
|---|---|
| unaware | hollow, muted stroke |
| aware | light gray fill |
| reacting | mid gray fill |
| affected | solid ink |
| recovered | ring: hollow with 2px ink stroke |
| adopted | solid ink (terminal state for launches) |
| opposed | ring with mid-gray fill |

Clusters: radius = log10(population), fill = population-weighted mean intensity on a gray ramp. Flows are thin ink lines with moving dashes.

## Accent

None. No accent color is used anywhere. Positive vs negative impact is encoded as filled vs hollow and ring vs solid, per the spec.

## Accessibility

- Contrast: ink and muted on bg pass WCAG AA in both themes (checked values above).
- All controls are native `<button>`, `<input type="range">`, `<select>`; visible focus rings in ink.
- Space toggles play/pause when focus is not in a text field; arrow keys move the scrubber.
- Progress and notable moments are announced through an `aria-live="polite"` region in the chat panel.
- Bubbles are also listed in the Voices log, so nothing is only available by hovering the map.
