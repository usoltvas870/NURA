# Skill: FastAPI Patterns (NURA)

## Architecture (обязательно)
```
routes/ → services/ → repositories/ → models/
routes/ → schemas/
```
- Routes: только HTTP/WebSocket логика, вызов сервисов
- Services: бизнес-логика, AI вызовы, транзакции
- Repositories: data access (SQLAlchemy async)
- Schemas: Pydantic I/O валидация
- Models: SQLAlchemy модели, нет API/Services импортов

## Dependency Injection
```python
# api/deps.py
from core.repositories.user_repo import UserRepository
from core.services.user_service import UserService

async def get_user_service(
    db: AsyncSession = Depends(get_session),
) -> UserService:
    repo = UserRepository(db)
    return UserService(repo)

# api/routes/users.py
@router.get("/{user_id}")
async def get_user(
    user_id: int,
    service: UserService = Depends(get_user_service),
) -> UserResponse:
    return await service.get_user(user_id)
```

## Pydantic v2
```python
from pydantic import BaseModel, Field, ConfigDict

class UserCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    username: str = Field(..., min_length=3, max_length=50, pattern=r"^[a-zA-Z0-9_]+$")
    email: EmailStr
```

## Async SQLAlchemy 2.0
```python
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

class UserRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def get_by_id(self, user_id: int) -> User | None:
        result = await self._session.execute(
            select(User).where(User.id == user_id)
        )
        return result.scalar_one_or_none()
```

## Error Handling
```python
from fastapi import HTTPException, status

class UserNotFoundError(Exception):
    pass

# service raises domain exception
# route catches and converts to HTTP
@router.get("/{user_id}")
async def get_user(user_id: int, service = Depends(get_user_service)):
    try:
        return await service.get_user(user_id)
    except UserNotFoundError:
        raise HTTPException(status_code=404, detail="User not found")
```

## Testing
```python
# tests/conftest.py
@pytest_asyncio.fixture
async def client(db_session):
    app.dependency_overrides[get_session] = lambda: db_session
    async with AsyncClient(app=app, base_url="http://test") as ac:
        yield ac

async def test_create_user(client: AsyncClient):
    response = await client.post("/api/v1/users", json={"username": "test"})
    assert response.status_code == 201
```

## Anti-patterns
- ❌ Service вызывает другой Service напрямую через конструктор → используй DI
- ❌ Route содержит SQL запросы → вынеси в Repository
- ❌ Model содержит Pydantic логику/валидацию → Model = DB, Schema = I/O
- ❌ Огромные файлы >500 строк → раздели на модули
- ❌ Синхронные вызовы в async route → используй run_in_executor или асинхронную библиотеку
- ❌ Голые dict в ответах → всегда Pydantic response_model
