---
name: sqlalchemy
description: SQLAlchemy 2.0 async patterns for PostgreSQL — session management, queries, relationships, and N+1 detection. Use when working with core/models/ or core/repositories/.
---

# SQLAlchemy 2.0 Async Patterns (NURA)

## Engine & Session Setup
```python
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase

engine = create_async_engine(
    "postgresql+asyncpg://user:pass@localhost:5432/nura",
    echo=True,          # SQL logging (debug only)
    pool_size=20,
    max_overflow=10,
    pool_pre_ping=True,
)

async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

class Base(DeclarativeBase):
    pass
```

## Repository Pattern (NURA standard)
```python
from sqlalchemy import select, update, delete
from sqlalchemy.ext.asyncio import AsyncSession

class UserRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def get_by_id(self, user_id: int) -> User | None:
        result = await self._session.execute(
            select(User).where(User.id == user_id)
        )
        return result.scalar_one_or_none()

    async def get_by_email(self, email: str) -> User | None:
        result = await self._session.execute(
            select(User).where(User.email == email)
        )
        return result.scalar_one_or_none()

    async def create(self, **kwargs) -> User:
        user = User(**kwargs)
        self._session.add(user)
        await self._session.commit()
        await self._session.refresh(user)
        return user

    async def update(self, user_id: int, **kwargs) -> User | None:
        result = await self._session.execute(
            update(User).where(User.id == user_id).values(**kwargs).returning(User)
        )
        await self._session.commit()
        return result.scalar_one_or_none()

    async def delete(self, user_id: int) -> bool:
        result = await self._session.execute(
            delete(User).where(User.id == user_id)
        )
        await self._session.commit()
        return result.rowcount > 0

    async def list_active(self, skip: int = 0, limit: int = 100) -> list[User]:
        result = await self._session.execute(
            select(User).where(User.is_active == True).offset(skip).limit(limit)
        )
        return list(result.scalars().all())
```

## Relationships & Eager Loading
```python
from sqlalchemy import ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship, selectinload

class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    reports: Mapped[list["Report"]] = relationship(back_populates="user", lazy="selectin")

class Report(Base):
    __tablename__ = "reports"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    user: Mapped["User"] = relationship(back_populates="reports", lazy="joined")

# Eager load to avoid N+1
async def get_user_with_reports(user_id: int) -> User | None:
    result = await session.execute(
        select(User)
        .options(selectinload(User.reports))
        .where(User.id == user_id)
    )
    return result.scalar_one_or_none()
```

## N+1 Detection
```python
# ❌ N+1: each report triggers separate query
async def get_users_with_reports_bad():
    users = await session.execute(select(User))
    for user in users.scalars():
        print(user.reports)  # Triggers query each time

# ✅ Fixed: eager load
async def get_users_with_reports_good():
    users = await session.execute(
        select(User).options(selectinload(User.reports))
    )
    for user in users.scalars():
        print(user.reports)  # Already loaded
```

## Bulk Operations
```python
from sqlalchemy import insert

# Bulk insert
await session.execute(
    insert(User).values([
        {"email": "a@test.com", "name": "A"},
        {"email": "b@test.com", "name": "B"},
    ])
)
await session.commit()

# Bulk update
await session.execute(
    update(User).where(User.is_active == False).values(is_active=True)
)
await session.commit()
```

## Transactions & Error Handling
```python
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

async def safe_create(email: str) -> User:
    try:
        user = User(email=email)
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user
    except IntegrityError:
        await session.rollback()
        raise UserAlreadyExistsError(email)
    except SQLAlchemyError:
        await session.rollback()
        raise
```

## Pagination
```python
async def paginated_query(page: int = 1, per_page: int = 20):
    result = await session.execute(
        select(User)
        .order_by(User.created_at.desc())
        .offset((page - 1) * per_page)
        .limit(per_page)
    )
    return list(result.scalars().all())
```

## Hybrid Attributes (computed fields)
```python
from sqlalchemy.ext.hybrid import hybrid_property

class Subscription(Base):
    __tablename__ = "subscriptions"

    start_date: Mapped[datetime]
    end_date: Mapped[datetime]

    @hybrid_property
    def is_active(self) -> bool:
        return self.start_date <= datetime.utcnow() <= self.end_date
```

## Anti-patterns
- ❌ sync_session в async коде → всегда AsyncSession
- ❌ Не вызывать commit → изменения теряются
- ❌ N+1 через relationship без eager load → используй selectinload/joinedload
- ❌ Огромные IN () без batching → разбивай на chunks по 1000
- ❌ expire_on_commit=True + обращение после commit → используй refresh() или expire_on_commit=False
