from fastapi import Header, HTTPException

from core.database import get_async_sessionmaker
from core.models import User
from core.repositories.user import UserRepository


async def get_current_web_user(
    x_session_id: str = Header(..., alias="X-Session-Id"),
) -> User:
    session_factory = get_async_sessionmaker()
    user_repo = UserRepository(session_factory)
    user = await user_repo.get_by_web_session_id(x_session_id)
    if user is None:
        raise HTTPException(status_code=404, detail="Сессия не найдена")
    return user
