from core.models import User


async def can_access_full_report(user: User) -> bool:
    return user.subscription_status == "premium"
