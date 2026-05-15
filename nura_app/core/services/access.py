from core.models import User


async def can_access_full_report(user: User, birth_date: str) -> tuple[bool, str]:
    if user.subscription_status == "premium" and birth_date == user.birth_date:
        return True, "subscription"
    if birth_date != user.birth_date:
        return False, "other_person"
    return False, "pay"
