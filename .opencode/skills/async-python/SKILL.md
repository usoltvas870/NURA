---
name: async-python
description: Master Python asyncio, concurrent programming, and async/await patterns for high-performance applications. Use when building async APIs, concurrent systems, or I/O-bound applications requiring non-blocking operations.
---

# Async Python Patterns

Comprehensive guidance for implementing asynchronous Python applications using asyncio, concurrent programming patterns, and async/await for building high-performance, non-blocking systems.

## When to Use This Skill

- Building async web APIs (FastAPI, aiohttp)
- Implementing concurrent I/O operations (database, file, network)
- Developing real-time applications (WebSocket servers)
- Processing multiple independent tasks simultaneously
- Building microservices with async communication
- Implementing async background tasks and queues

## Sync vs Async

| Use Case | Recommended |
|----------|------------|
| Many concurrent network/DB calls | `asyncio` |
| CPU-bound computation | `multiprocessing` or thread pool |
| Mixed I/O + CPU | Offload CPU work with `asyncio.to_thread()` |
| Simple scripts, few connections | Sync (simpler) |
| Web APIs with high concurrency | Async frameworks (FastAPI) |

**Key Rule:** Stay fully sync or fully async within a call path. Mixing creates hidden blocking.

## Core Patterns

### Basic Async/Await
```python
import asyncio

async def fetch_data(url: str) -> dict:
    await asyncio.sleep(1)
    return {"url": url, "data": "result"}
```

### Concurrent Execution with gather()
```python
async def fetch_user(user_id: int) -> dict:
    await asyncio.sleep(0.5)
    return {"id": user_id, "name": f"User {user_id}"}

async def fetch_all_users(user_ids: list[int]) -> list[dict]:
    tasks = [fetch_user(uid) for uid in user_ids]
    return await asyncio.gather(*tasks)
```

### Task Creation and Management
```python
async def background_task(name: str, delay: int):
    print(f"{name} started")
    await asyncio.sleep(delay)
    print(f"{name} completed")
    return f"Result from {name}"

async def main():
    task1 = asyncio.create_task(background_task("Task 1", 2))
    task2 = asyncio.create_task(background_task("Task 2", 1))
    print("Main: doing other work")
    await asyncio.sleep(0.5)
    result1 = await task1
    result2 = await task2
```

### Error Handling
```python
async def safe_operation(item_id: int) -> dict | None:
    try:
        return await risky_operation(item_id)
    except ValueError as e:
        print(f"Error: {e}")
        return None

async def process_items(item_ids: list[int]):
    tasks = [safe_operation(iid) for iid in item_ids]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    successful = [r for r in results if r is not None and not isinstance(r, Exception)]
    return successful
```

### Timeout Handling
```python
async def with_timeout():
    try:
        result = await asyncio.wait_for(slow_operation(5), timeout=2.0)
    except asyncio.TimeoutError:
        print("Operation timed out")
```

### Async Context Manager
```python
class AsyncResource:
    async def __aenter__(self):
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()
```

### asyncio.to_thread (CPU-bound offload)
```python
def cpu_intensive(data: str) -> str:
    import hashlib
    return hashlib.sha256(data.encode()).hexdigest()

async def handler(data: str) -> str:
    result = await asyncio.to_thread(cpu_intensive, data)
    return result
```

## Common Pitfalls

### Forgetting await
```python
# Wrong — returns coroutine, doesn't execute
result = async_function()

# Correct
result = await async_function()
```

### Blocking the Event Loop
```python
# Wrong — blocks
import time
async def bad():
    time.sleep(1)

# Correct
async def good():
    await asyncio.sleep(1)
```

### Mixing Sync and Async
```python
# Wrong
def sync_fn():
    result = await async_fn()

# Correct
def sync_fn():
    result = asyncio.run(async_fn())
```

## Testing Async Code
```python
import pytest

@pytest.mark.asyncio
async def test_async_function():
    result = await fetch_data("https://api.example.com")
    assert result is not None
```

## Async SQLAlchemy 2.0 (NURA)
```python
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker

engine = create_async_engine(DATABASE_URL)
async_session = async_sessionmaker(engine, class_=AsyncSession)

async def get_user(user_id: int) -> User | None:
    async with async_session() as session:
        result = await session.execute(select(User).where(User.id == user_id))
        return result.scalar_one_or_none()
```

## AIOHTTP (for external API calls)
```python
import aiohttp

async def fetch_json(url: str) -> dict:
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            resp.raise_for_status()
            return await resp.json()

async def fetch_many(urls: list[str]) -> list[dict]:
    async with aiohttp.ClientSession() as session:
        tasks = [fetch_one(session, url) for url in urls]
        return await asyncio.gather(*tasks, return_exceptions=True)
```
