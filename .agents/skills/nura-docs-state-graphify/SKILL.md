---
name: nura-docs-state-graphify
description: Assess NURA architecture, documentation, STATE.md, and Graphify obligations. Use for Python modules, routes, services, repositories, integrations, dependency-direction changes, material documentation changes, or deciding whether STATE.md or Graphify must be updated; do not use for purely visual, small text, skill, or reviewer-agent changes.
---

# NURA docs, state, and Graphify assessment

Perform the assessment without waiting for an owner reminder. Report exactly one result for every relevant task: Graphify update is not required; Graphify update was completed; or Graphify update is deferred for a concrete risk.

Do not update Graphify for CSS, purely visual HTML, images, design previews, small text edits, small changes inside an existing function, skills, or reviewer-agent files. Consider it for new Python packages/modules, services, routes/controllers, repositories, cross-layer import changes, architecture refactors, significant moves, or removal of substantial Python components.

Run `graphify update` without separate owner prompting only when the approved task changes Python architecture, implementation/tests and Graphify 0.9.7 health checks pass, hooks stay disabled, a `graphify-out` baseline (paths, count, sizes, SHA-256) exists, unrelated changes do not overlap, output is confined to `graphify-out`, and the diff is expected and reviewed before staging. If the delta is large or unexpected, stop, restore only the recorded `graphify-out` baseline, and report it. Never restore automated hooks.

Update `STATE.md` only for material project-state changes. Include the Graphify assessment in the final report.
