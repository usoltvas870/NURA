---
name: NURA Infrastructure
description: Docker, deployment, migrations, and workflow safety
applyTo: "nura_app/Dockerfile,nura_app/docker-compose*.yml,nura_app/nginx/**,nura_app/alembic/**,.github/workflows/**"
---

- Never expose secrets in code, logs, images, workflow output, or client bundles.
- Keep PostgreSQL and Redis private; expose only required application ports.
- Make migrations reversible where practical and inspect generated SQL before production use.
- Never deploy, push, restart production, or run production migrations without explicit user approval.
- After infrastructure changes, validate the Compose configuration before deployment.
