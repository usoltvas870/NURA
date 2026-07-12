---
name: nura-report-render-qa
description: Validate NURA HTML and PDF report rendering. Use for report templates, report CSS, Jinja data, WeasyPrint, PDF export, page breaks, report fonts, or report assets; do not use for unrelated UI or backend tasks.
---

# NURA report render QA

Read `nura_app/templates/reports/AGENTS.md`. For a redesign, follow the required progression: static preview, one control chapter, browser render, WeasyPrint render, then the full template. Test full and mini reports separately. Check browser HTML at the relevant viewport with visual evidence for layout, overflow, fonts, background assets, and print styles; HTML success never proves PDF correctness. Verify WeasyPrint support before using CSS features. On Windows, set `WEASYPRINT_DLL_DIRECTORIES=C:\msys64\mingw64\bin` only for the current session and never change global `PATH`.

Verify that the PDF is created and parseable, page count is reasonable, first/last pages and extracted text are available, and there are no empty pages or clipped text. Test page breaks, long headings and paragraphs, optional sections, tables/lists, images, fonts, backgrounds, footer/header, and Cyrillic. Do not install native/system dependencies without approval. Keep temporary PDFs in `C:\tmp` and never add smoke PDFs to Git.

Always escape user-provided text. During visual work, do not change the report data schema.
