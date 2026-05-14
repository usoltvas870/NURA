"""
Matrix of Destiny full calculation service.
Based on birth date numerology mapping to the 22 Major Arcana.
Method by Natalia Ladini.
"""

from core.schemas import MatrixData

ARCANA: dict[int, dict[str, str]] = {
    1:  {"name": "Маг",               "emoji": "✨",  "key": "Воля, мастерство, начало"},
    2:  {"name": "Верховная Жрица",    "emoji": "📿",  "key": "Интуиция, тайна, подсознание"},
    3:  {"name": "Императрица",        "emoji": "👑",  "key": "Изобилие, природа, творчество"},
    4:  {"name": "Император",          "emoji": "🏛️", "key": "Структура, власть, порядок"},
    5:  {"name": "Иерофант",           "emoji": "📖",  "key": "Учение, традиция, наставничество"},
    6:  {"name": "Влюблённые",         "emoji": "💕",  "key": "Выбор, гармония, партнёрство"},
    7:  {"name": "Колесница",          "emoji": "🚀",  "key": "Прорыв, победа, решимость"},
    8:  {"name": "Сила",               "emoji": "🦁",  "key": "Внутренняя сила, смелость"},
    9:  {"name": "Отшельник",          "emoji": "🏔️", "key": "Мудрость, уединение, поиск"},
    10: {"name": "Колесо Фортуны",     "emoji": "🎡",  "key": "Судьба, циклы, перемены"},
    11: {"name": "Справедливость",     "emoji": "⚖️",  "key": "Карма, баланс, истина"},
    12: {"name": "Повешенный",         "emoji": "🔄",  "key": "Пауза, переосмысление, жертва"},
    13: {"name": "Смерть",             "emoji": "💀",  "key": "Трансформация, обновление"},
    14: {"name": "Умеренность",        "emoji": "🌊",  "key": "Баланс, гармония, равновесие"},
    15: {"name": "Дьявол",             "emoji": "⛓️",  "key": "Тень, зависимость, искушение"},
    16: {"name": "Башня",              "emoji": "🗼",  "key": "Разрушение, прозрение, освобождение"},
    17: {"name": "Звезда",             "emoji": "⭐",  "key": "Надежда, вдохновение, вера"},
    18: {"name": "Луна",               "emoji": "🌙",  "key": "Иллюзии, подсознание, страхи"},
    19: {"name": "Солнце",             "emoji": "☀️",  "key": "Радость, успех, витальность"},
    20: {"name": "Суд",                "emoji": "📯",  "key": "Пробуждение, призвание, переоценка"},
    21: {"name": "Мир",                "emoji": "🌍",  "key": "Завершение, целостность, реализация"},
    22: {"name": "Шут",                "emoji": "🎭",  "key": "Свобода, новое начало, спонтанность"},
}


def sum_digits(n: int) -> int:
    while n > 22:
        n = sum(int(d) for d in str(n))
    return n


def parse_birth_date(date_str: str) -> tuple[int, int, int]:
    parts = date_str.strip().split(".")
    return int(parts[0]), int(parts[1]), int(parts[2])


class MatrixService:
    @staticmethod
    def get_archetype_name(number: int) -> str:
        return ARCANA.get(number, {}).get("name", "Неизвестный")

    @staticmethod
    def calculate(birth_date: str) -> MatrixData:
        day, month, year = parse_birth_date(birth_date)

        # --- Базовые углы ---
        A = sum_digits(day)
        B = sum_digits(month)
        C = sum_digits(sum(int(d) for d in str(year)))
        D = sum_digits(A + B + C)

        # --- Центр ---
        E = sum_digits(A + B + C + D)

        # --- Производные зоны ---
        talent = sum_digits(E + B)
        comfort = sum_digits(E + A)
        portrait = sum_digits(E + C)

        # --- Кармический хвост ---
        karmic_tail = [D, E, B]

        # --- Внутренние точки ---
        inner_f = sum_digits(A + B)
        inner_g = sum_digits(B + C)
        inner_h = sum_digits(C + D)
        inner_i = sum_digits(D + A)

        # --- Линии ---
        sky_line = [inner_f, E, inner_h]
        earth_line = [inner_g, E, inner_i]
        relationship_line = [A, E, C]
        money_line = [B, E, D]

        # --- Точка отношений ---
        relationship_point = sum_digits(A + C)

        return MatrixData(
            birth_date=birth_date,
            center=E,
            top=B,
            bottom=D,
            left=A,
            right=C,
            talent_zone=talent,
            comfort_zone=comfort,
            portrait_zone=portrait,
            karmic_tail=karmic_tail,
            inner_f=inner_f,
            inner_g=inner_g,
            inner_h=inner_h,
            inner_i=inner_i,
            sky_line=sky_line,
            earth_line=earth_line,
            relationship_line=relationship_line,
            money_line=money_line,
            relationship_point=relationship_point,
            arcana_names={
                "center": ARCANA[E]["name"],
                "top": ARCANA[B]["name"],
                "bottom": ARCANA[D]["name"],
                "left": ARCANA[A]["name"],
                "right": ARCANA[C]["name"],
                "talent_zone": ARCANA[talent]["name"],
                "comfort_zone": ARCANA[comfort]["name"],
                "portrait_zone": ARCANA[portrait]["name"],
                "inner_f": ARCANA[inner_f]["name"],
                "inner_g": ARCANA[inner_g]["name"],
                "inner_h": ARCANA[inner_h]["name"],
                "inner_i": ARCANA[inner_i]["name"],
            },
        )

    @staticmethod
    def format_for_prompt(matrix_data: "MatrixData | dict") -> str:
        if isinstance(matrix_data, dict):
            matrix_data = MatrixData(**matrix_data)
        md = matrix_data
        lines = [
            f"Дата рождения: {md.birth_date}",
            "",
            "== Основные позиции ==",
            f"Центр (главный архетип): {ARCANA[md.center]['emoji']} {ARCANA[md.center]['name']} ({md.center})",
            f"Верх (небо): {ARCANA[md.top]['emoji']} {ARCANA[md.top]['name']} ({md.top})",
            f"Низ (земля): {ARCANA[md.bottom]['emoji']} {ARCANA[md.bottom]['name']} ({md.bottom})",
            f"Лево (мужское): {ARCANA[md.left]['emoji']} {ARCANA[md.left]['name']} ({md.left})",
            f"Право (женское): {ARCANA[md.right]['emoji']} {ARCANA[md.right]['name']} ({md.right})",
            "",
            "== Зоны ==",
            f"Зона талантов: {ARCANA[md.talent_zone]['emoji']} {ARCANA[md.talent_zone]['name']} ({md.talent_zone})",
            f"Зона комфорта: {ARCANA[md.comfort_zone]['emoji']} {ARCANA[md.comfort_zone]['name']} ({md.comfort_zone})",
            f"Портретная зона: {ARCANA[md.portrait_zone]['emoji']} {ARCANA[md.portrait_zone]['name']} ({md.portrait_zone})",
            "",
            "== Кармический хвост ==",
            f"Причина (низ): {ARCANA[md.karmic_tail[0]]['emoji']} {ARCANA[md.karmic_tail[0]]['name']} ({md.karmic_tail[0]})",
            f"Следствие (центр): {ARCANA[md.karmic_tail[1]]['emoji']} {ARCANA[md.karmic_tail[1]]['name']} ({md.karmic_tail[1]})",
            f"Урок (верх): {ARCANA[md.karmic_tail[2]]['emoji']} {ARCANA[md.karmic_tail[2]]['name']} ({md.karmic_tail[2]})",
            "",
            "== Внутренние точки ==",
            f"Кармический дар (F): {ARCANA[md.inner_f]['emoji']} {ARCANA[md.inner_f]['name']} ({md.inner_f})",
            f"Линия отца (G): {ARCANA[md.inner_g]['emoji']} {ARCANA[md.inner_g]['name']} ({md.inner_g})",
            f"Денежный канал (H): {ARCANA[md.inner_h]['emoji']} {ARCANA[md.inner_h]['name']} ({md.inner_h})",
            f"Линия матери (I): {ARCANA[md.inner_i]['emoji']} {ARCANA[md.inner_i]['name']} ({md.inner_i})",
            "",
            "== Линии ==",
            f"Линия неба (духовное): {ARCANA[md.sky_line[0]]['emoji']} {ARCANA[md.sky_line[0]]['name']} ({md.sky_line[0]}) → {ARCANA[md.sky_line[1]]['emoji']} {ARCANA[md.sky_line[1]]['name']} ({md.sky_line[1]}) → {ARCANA[md.sky_line[2]]['emoji']} {ARCANA[md.sky_line[2]]['name']} ({md.sky_line[2]})",
            f"Линия земли (материальное): {ARCANA[md.earth_line[0]]['emoji']} {ARCANA[md.earth_line[0]]['name']} ({md.earth_line[0]}) → {ARCANA[md.earth_line[1]]['emoji']} {ARCANA[md.earth_line[1]]['name']} ({md.earth_line[1]}) → {ARCANA[md.earth_line[2]]['emoji']} {ARCANA[md.earth_line[2]]['name']} ({md.earth_line[2]})",
            f"Линия отношений: {ARCANA[md.relationship_line[0]]['emoji']} {ARCANA[md.relationship_line[0]]['name']} ({md.relationship_line[0]}) → {ARCANA[md.relationship_line[1]]['emoji']} {ARCANA[md.relationship_line[1]]['name']} ({md.relationship_line[1]}) → {ARCANA[md.relationship_line[2]]['emoji']} {ARCANA[md.relationship_line[2]]['name']} ({md.relationship_line[2]})",
            f"Линия денег: {ARCANA[md.money_line[0]]['emoji']} {ARCANA[md.money_line[0]]['name']} ({md.money_line[0]}) → {ARCANA[md.money_line[1]]['emoji']} {ARCANA[md.money_line[1]]['name']} ({md.money_line[1]}) → {ARCANA[md.money_line[2]]['emoji']} {ARCANA[md.money_line[2]]['name']} ({md.money_line[2]})",
            "",
            f"Точка отношений: {ARCANA[md.relationship_point]['emoji']} {ARCANA[md.relationship_point]['name']} ({md.relationship_point})",
        ]
        return "\n".join(lines)

    @staticmethod
    def format_for_report(matrix_data: "MatrixData | dict") -> dict:
        if isinstance(matrix_data, dict):
            matrix_data = MatrixData(**matrix_data)
        md = matrix_data

        def a(n: int) -> dict:
            return {
                "number": n,
                "name": ARCANA[n]["name"],
                "emoji": ARCANA[n]["emoji"],
                "key": ARCANA[n]["key"],
            }

        return {
            "birth_date": md.birth_date,
            "center": a(md.center),
            "corners": {
                "top": a(md.top),
                "bottom": a(md.bottom),
                "left": a(md.left),
                "right": a(md.right),
            },
            "zones": {
                "talent": a(md.talent_zone),
                "comfort": a(md.comfort_zone),
                "portrait": a(md.portrait_zone),
            },
            "karmic_tail": {
                "cause": a(md.karmic_tail[0]),
                "effect": a(md.karmic_tail[1]),
                "lesson": a(md.karmic_tail[2]),
            },
            "inner_points": {
                "f": a(md.inner_f),
                "g": a(md.inner_g),
                "h": a(md.inner_h),
                "i": a(md.inner_i),
            },
            "lines": {
                "sky": [a(v) for v in md.sky_line],
                "earth": [a(v) for v in md.earth_line],
                "relationship": [a(v) for v in md.relationship_line],
                "money": [a(v) for v in md.money_line],
            },
            "relationship_point": a(md.relationship_point),
        }
