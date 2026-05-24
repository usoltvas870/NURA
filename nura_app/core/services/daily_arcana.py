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


def get_today_arcana_with_name(birth_date: str, arcana_names: dict) -> dict:
    number = calculate_daily_arcana(birth_date)
    name = arcana_names.get(str(number), arcana_names.get(number, f"Аркан {number}"))
    return {"number": number, "name": name}


def calculate_spread_arcanas(birth_date: str, count: int = 3) -> list[int]:
    daily = calculate_daily_arcana(birth_date)
    return [(daily + i * 7) % 22 + 1 for i in range(count)]
