from datetime import date


def _reduce_to_arcana(value: int) -> int:
    while value > 22:
        value = sum(int(d) for d in str(value))
    return value


def daily_arcana_number(today: date | None = None) -> int:
    """Единый алгоритм: сумма цифр DDMMYYYY, редукция до 1–22."""
    today = today or date.today()
    total = sum(int(d) for d in f"{today.day:02d}{today.month:02d}{today.year}")
    return _reduce_to_arcana(total)


def personalize_arcana(today: date | None, center_arcana: int) -> int:
    """Персонализированный аркан = daily + center → редукция до 1–22."""
    base = daily_arcana_number(today)
    total = base + center_arcana
    result = _reduce_to_arcana(total)
    return result or 22


def calculate_daily_arcana(birth_date: str) -> int:
    """Совместимая обёртка — принимает birth_date для обратной совместимости."""
    return daily_arcana_number()


def get_today_arcana_with_name(birth_date: str, arcana_names: dict) -> dict:
    number = daily_arcana_number()
    name = arcana_names.get(str(number), arcana_names.get(number, f"Аркан {number}"))
    return {"number": number, "name": name}


def calculate_spread_arcanas(birth_date: str, count: int = 3) -> list[int]:
    daily = daily_arcana_number()
    return [(daily + i * 7) % 22 + 1 for i in range(count)]
