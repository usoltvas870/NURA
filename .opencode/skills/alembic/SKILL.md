---
name: alembic
description: Alembic migration patterns for SQLAlchemy 2.0 async — generating, reviewing, and applying database migrations for PostgreSQL. Use when changing core/models/ or running alembic commands.
---

# Alembic Migration Patterns (NURA)

## NURA Commands
```bash
# Generate migration
alembic revision --autogenerate -m "add_user_fields"

# Apply all
alembic upgrade head

# Rollback one step
alembic downgrade -1

# View history
alembic history

# View current
alembic current
```

## Async Migration Setup
```python
# alembic/env.py
from sqlalchemy.ext.asyncio import create_async_engine
from alembic import context
from core.config import settings
from core.models import Base  # noqa: F401 — import all models

async def run_migrations_online():
    connectable = create_async_engine(settings.DATABASE_URL)

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

def do_run_migrations(connection):
    context.configure(connection=connection, target_metadata=Base.metadata)
    with context.begin_transaction():
        context.run_migrations()
```

## Migration Structure
```
alembic/
├── versions/
│   ├── 0001_initial.py
│   ├── 0002_add_user_fields.py
│   └── 0003_add_subscriptions.py
├── env.py
├── script.py.mako
└── alembic.ini
```

## Writing Migrations

### New table
```python
"""add_subscriptions

Revision ID: 0003
Revises: 0002
"""
from typing import Sequence
from alembic import op
import sqlalchemy as sa

revision: str = "0003"
down_revision: str | None = "0002"

def upgrade() -> None:
    op.create_table(
        "subscriptions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("plan", sa.String(length=50), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_subscriptions_user_id", "subscriptions", ["user_id"])

def downgrade() -> None:
    op.drop_index("ix_subscriptions_user_id")
    op.drop_table("subscriptions")
```

### Add column with data migration
```python
def upgrade() -> None:
    op.add_column("users", sa.Column("display_name", sa.String(100), nullable=True))
    # Backfill data
    op.execute("UPDATE users SET display_name = username WHERE display_name IS NULL")
    op.alter_column("users", "display_name", nullable=False)
```

### Add index
```python
def upgrade() -> None:
    op.create_index("ix_users_email_lower", "users", [sa.text("lower(email)")])
```

### Drop column
```python
def upgrade() -> None:
    op.drop_column("users", "old_field")
```

## Review Checklist
- 🔴 down_revision указывает на правильную предыдущую миграцию
- 🔴 Внешние ключи используют ondelete (CASCADE/SET NULL)
- 🔴 Новые NOT NULL колонки имеют server_default или backfill
- 🟡 Есть индексы на поля в WHERE/JOIN/ORDER BY
- 🟡 Boolean колонки используют server_default, а не nullable=True
- 💭 Имена соответствуют конвенции: ix_<table>_<column>, fk_<table>_<ref>
