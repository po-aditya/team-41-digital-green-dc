---
inclusion: always
---

# Design tokens (farmerchat-ui)

The whole UI uses ONE visual language, green, matching the attached reference
(crimson/pink -> green). Define every value below as a CSS variable; never
hard-code hex in components. WCAG AA contrast; never colour alone for state
(always icon + text label).

## Palette (only these + neutral greys)
- `--green-deep: #1B5E20`   (critical text, button hover)
- `--green-brand: #2E7D32`  (primary buttons, filled progress, selected ring)
- `--green-brand-alt: #2F6B3A`
- `--green-light: #E5F0E3`  / `--green-light-2: #C8E6C9` (tints, unfilled progress)
- `--white: #FFFFFF`
- `--page-tint: #F7F8F5`
- `--ink: #1D231C`          `--muted: #5D6A5A`   `--line: #DDE3D8`
- Backdrop gradient blobs: `#E8F5E9`, `#C8E6C9`, `#F7FBF6`
- Semantic (small chips only, icon+label): amber text `#8A4B0F` on `#FBEEDD`
  (deferred/warning); deep red only for critical/blocked.

## Shape / type
- Phone frame radius 44-48px, diffuse shadow, 9:41 status bar, home pill.
- Console cards radius 20px, denser, never the large phone radius.
- Fonts: Poppins (UI/Latin), Noto Sans Devanagari (Hindi). Google Fonts.
- Option rows: radius 16-20px, height 56-60px, 1px `--line` border, 24px radio
  with 2px green ring; selected = `--green-light` tint + filled radio + spring.
- Primary button: full-width pill ~60px, white UPPERCASE bold + letter-spacing
  on `--green-brand`, hover `--green-deep`, disabled until a choice is made.
- Progress: segmented pill, one segment per step, filled `--green-brand`, rest
  `--green-light-2`, small gaps. Reused for the console pipeline strip.

## Motion
- Sheet rises with a spring; chips cross-fade; counters tick; connector pulses
  console->phone; JAAKBOT shows a soft pulsing ring while listening.
- 60fps, no layout shift. Honour `prefers-reduced-motion`: no confetti (static
  green check), no momentum, minimal transitions.

## Layout
- Target 1440x900 projector first (body >=14px, key numbers >=20px).
- <1100px: stack into tabs (Console | Phone). Phone works alone at 360px with
  no Hindi clipping.

## Do NOT
- Do not copy the reference image's content (shopping copy, brand, emoji).
- No emoji anywhere in the UI. Celebration is confetti/motion only.
