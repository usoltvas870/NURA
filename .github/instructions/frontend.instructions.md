---
name: NURA Frontend
description: Frontend, templates, and report UI rules
applyTo: "*.html,frontend/**,nura_app/templates/**/*.{html,css,js}"
---

- Use vanilla HTML, CSS, and JavaScript.
- Preserve the existing dark premium black, deep-green, and orange visual language.
- Build mobile-first and preserve keyboard navigation, focus states, and readable contrast.
- Escape user-controlled content and avoid unsafe `innerHTML`.
- For report templates, verify both browser rendering and WeasyPrint compatibility.
- Use Playwright MCP for meaningful UI changes and report the viewport tested.
