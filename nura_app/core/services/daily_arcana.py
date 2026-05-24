from datetime import date


def calculate_daily_arcana(birth_date: str) -> int:
    day, month, year = map(int, birth_date.split("."))
    today = date.today()
    day_of_year = today.timetuple().tm_yday

    total = sum(int(d) for d in str(day_of_year))
    total += sum(int(d) for d in str(day))
    total += sum(int(d) for d in str(month))

    while total > 22:
        total = sum(int(d) for d in str(total))

    return total


def calculate_spread_arcanas(birth_date: str, count: int = 3) -> list[int]:
    daily = calculate_daily_arcana(birth_date)
    return [(daily + i * 7) % 22 + 1 for i in range(count)]
