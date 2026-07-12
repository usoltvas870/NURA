---
name: nura-pwa-visual-qa
description: Verify visual changes to NURA PWA or landing UI. Use for frontend/pwa/app, PWA pages and shared assets, landing UI, responsive work, visual regressions, or browser QA; do not use for non-visual backend-only changes.
---

# NURA PWA visual QA

Read `frontend/pwa/app/AGENTS.md`, `docs/pwa/PWA_NORTH_STAR_DESIGN.md`, `docs/pwa/PWA_PAGE_CONTRACTS.md`, and `docs/pwa/PWA_IMPLEMENTATION_RULES.md`.

Preserve IDs, `data-*` attributes, JavaScript hooks, auth/payment hooks, and API contracts. Keep the app shell within the approved ~520px maximum, preserve the working `data-theme="dark"` theme and `prefers-reduced-motion` behavior, and check only changed pages at 360×800, 390×844, and 430×932. Capture screenshots and compare them to the approved Variant B direction.

Check overflow, tabbar and safe-area, sticky/fixed elements, keyboard and scrolling, skeleton/loading/empty states, applicable guest/authenticated/subscriber states, console errors, failed/404 resources, images, touch targets, and text clipping. Confirm the CTA mapping and that a guest cannot see report-only actions; the daily-card area is hidden or replaced with a gentle authorization CTA for guests. A clean console is not sufficient visual QA; reject generic-dashboard drift.

Keep the implementation iteration-scoped: begin the rollout with `index.html` only, change one page per iteration, do not broaden into backend/API/auth/payment work, and do not add global CSS without approval.
