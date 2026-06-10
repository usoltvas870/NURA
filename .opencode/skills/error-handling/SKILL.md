# Skill: Error Handling (Python)

## Domain Exceptions
```python
class DomainError(Exception):
    """Base domain exception"""
    def __init__(self, message: str, code: str | None = None):
        self.message = message
        self.code = code
        super().__init__(self.message)

class UserNotFoundError(DomainError): ...
class PaymentFailedError(DomainError): ...
class ReportGenerationError(DomainError): ...
```

## Service Layer
```python
from typing import Never

class UserService:
    async def get_user(self, user_id: int) -> User:
        user = await self._repo.get_by_id(user_id)
        if not user:
            raise UserNotFoundError(f"User {user_id} not found", code="USER_NOT_FOUND")
        return user
```

## API Layer → HTTP
```python
from fastapi import Request
from fastapi.responses import JSONResponse

@app.exception_handler(DomainError)
async def domain_error_handler(request: Request, exc: DomainError) -> JSONResponse:
    return JSONResponse(
        status_code=404 if isinstance(exc, UserNotFoundError) else 400,
        content={"error": exc.code or "DOMAIN_ERROR", "detail": exc.message},
    )
```

## Bot Layer → Telegram
```python
from aiogram.types import Message

async def safe_handler(message: Message, func):
    try:
        await func()
    except UserNotFoundError:
        await message.answer("Пользователь не найден")
    except DomainError as e:
        await message.answer(f"Ошибка: {e.message}")
        logger.warning("Domain error", exc_info=True)
    except Exception:
        await message.answer("Что-то пошло не так. Попробуйте позже.")
        logger.error("Unhandled error", exc_info=True)
```

## Anti-patterns
- ❌ `except Exception: pass` — немое проглатывание
- ❌ Голые `raise Exception("msg")` — используй domain exception hierarchy
- ❌ Stack trace в ответе пользователю → 500, log, generic message
- ❌ Ловить в каждом слое → лови на границе (route/handler), логируй в сервисе
- ❌ Не различать типы ошибок → всегда specific exception class
- ✅ `raise` from original exception — сохраняй chain
