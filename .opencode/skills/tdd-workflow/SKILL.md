# Skill: TDD Workflow

## Protocol
1. Red — напиши тест, который падает
2. Green — минимум кода чтобы тест прошёл
3. Refactor — улучши код сохраняя тесты зелёными

## NURA Test Setup
```python
# tests/conftest.py
@pytest_asyncio.fixture
async def db_session():
    engine = create_async_engine("postgresql+asyncpg://...")
    async with AsyncSession(engine) as session:
        yield session

@pytest_asyncio.fixture
async def client(db_session):
    app.dependency_overrides[get_session] = lambda: db_session
    async with AsyncClient(app=app, base_url="http://test") as ac:
        yield ac
```

## Test Patterns
### Service tests (mock repository)
```python
async def test_create_user__success():
    repo = AsyncMock(UserRepository)
    repo.create.return_value = User(id=1, username="test")
    service = UserService(repo)
    result = await service.create_user(UserCreate(username="test"))
    assert result.id == 1
```

### API tests (integration)
```python
async def test_get_user__returns_200(client: AsyncClient):
    response = await client.get("/api/v1/users/1")
    assert response.status_code == 200
    assert response.json()["username"] == "test"
```

### Repository tests (with real DB)
```python
async def test_get_by_id__returns_user(db_session: AsyncSession):
    repo = UserRepository(db_session)
    user = await repo.create(User(username="test"))
    found = await repo.get_by_id(user.id)
    assert found is not None
    assert found.username == "test"
```

## Что тестировать
- Service: business logic, edge cases, error paths
- Repository: CRUD, filters, relationships
- API: status codes, response shape, auth, validation errors
- Bot handlers: message flow, state transitions, keyboard clicks
- AI prompts: format, required fields, boundaries

## Что НЕ тестировать
- Тривиальные property/field access
- FastAPI/SQLAlchemy internals (они уже протестированы)
- Сторонние API (mock их)
- AI responses content (тестируй структуру, не семантику)
