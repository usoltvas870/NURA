from datetime import date


def _daily_arcana_number(today: date) -> int:
    total = sum(int(d) for d in f"{today.day:02d}{today.month:02d}{today.year}")
    while total > 22:
        total = sum(int(d) for d in str(total))
    return total


def _personal_arcana_number(today: date, center_arcana: int) -> int:
    base = _daily_arcana_number(today)
    total = base + center_arcana
    while total > 22:
        total = sum(int(d) for d in str(total))
    if total == 0:
        total = 22
    return total
