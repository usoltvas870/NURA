"""
Matrix of Destiny calculation service.
Based on birth date numerology mapping to the 22 Major Arcana.
"""

ARCANA_NAMES: dict[int, str] = {
    1: "Маг",
    2: "Верховная Жрица",
    3: "Императрица",
    4: "Император",
    5: "Иерофант",
    6: "Влюблённые",
    7: "Колесница",
    8: "Сила",
    9: "Отшельник",
    10: "Колесо Фортуны",
    11: "Справедливость",
    12: "Повешенный",
    13: "Смерть",
    14: "Умеренность",
    15: "Дьявол",
    16: "Башня",
    17: "Звезда",
    18: "Луна",
    19: "Солнце",
    20: "Суд",
    21: "Мир",
    22: "Шут",
}


def sum_digits(n: int) -> int:
    while n > 22:
        n = sum(int(d) for d in str(n))
    return n


def parse_birth_date(date_str: str) -> tuple[int, int, int]:
    parts = date_str.strip().split(".")
    day = int(parts[0])
    month = int(parts[1])
    year = int(parts[2])
    return day, month, year


class MatrixService:
    @staticmethod
    def calculate(birth_date: str) -> dict:
        day, month, year = parse_birth_date(birth_date)

        # Left corner — day
        left = sum_digits(day)

        # Top corner — month
        top = sum_digits(month)

        # Right corner — year sum
        right = sum_digits(sum(int(d) for d in str(year)))

        # Bottom corner — sum of left, top, right
        bottom = sum_digits(left + top + right)

        # Center — sum of all four corners
        center = sum_digits(left + top + right + bottom)

        # Talent zone — center + top
        talent_zone = sum_digits(center + top)

        # Comfort zone — center + left
        comfort_zone = sum_digits(center + left)

        # Portrait zone — center + bottom
        portrait_zone = sum_digits(center + bottom)

        # Karmic tail — bottom, center, top
        karmic_tail = [bottom, center, top]

        return {
            "birth_date": birth_date,
            "center": center,
            "top": top,
            "bottom": bottom,
            "left": left,
            "right": right,
            "talent_zone": talent_zone,
            "comfort_zone": comfort_zone,
            "portrait_zone": portrait_zone,
            "karmic_tail": karmic_tail,
            "arcana_names": {
                "center": ARCANA_NAMES.get(center, "Неизвестный"),
                "top": ARCANA_NAMES.get(top, "Неизвестный"),
                "bottom": ARCANA_NAMES.get(bottom, "Неизвестный"),
                "left": ARCANA_NAMES.get(left, "Неизвестный"),
                "right": ARCANA_NAMES.get(right, "Неизвестный"),
                "talent_zone": ARCANA_NAMES.get(talent_zone, "Неизвестный"),
                "comfort_zone": ARCANA_NAMES.get(comfort_zone, "Неизвестный"),
                "portrait_zone": ARCANA_NAMES.get(portrait_zone, "Неизвестный"),
            },
        }

    @staticmethod
    def format_for_prompt(matrix: dict) -> str:
        lines = [
            f"Дата рождения: {matrix['birth_date']}",
            f"Центр (главный архетип): {matrix['arcana_names']['center']} ({matrix['center']})",
            f"Верх (небо): {matrix['arcana_names']['top']} ({matrix['top']})",
            f"Низ (земля): {matrix['arcana_names']['bottom']} ({matrix['bottom']})",
            f"Лево (мужское): {matrix['arcana_names']['left']} ({matrix['left']})",
            f"Право (женское): {matrix['arcana_names']['right']} ({matrix['right']})",
            f"Зона талантов: {matrix['arcana_names']['talent_zone']} ({matrix['talent_zone']})",
            f"Зона комфорта: {matrix['arcana_names']['comfort_zone']} ({matrix['comfort_zone']})",
            f"Портретная зона: {matrix['arcana_names']['portrait_zone']} ({matrix['portrait_zone']})",
            f"Кармический хвост: {', '.join(f'{matrix[\"arcana_names\"].get(str(k), k)} ({k})' for k in matrix['karmic_tail'])}",
        ]
        return "\n".join(lines)
