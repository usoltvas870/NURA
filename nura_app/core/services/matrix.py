"""
Matrix of Destiny full calculation service.
Based on birth date numerology mapping to the 22 Major Arcana.
Method by Natalia Ladini.
"""

from datetime import date

from core.arcana_data import ARCANA
from core.schemas import MatrixData


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
    def calculate_year_arcana(birth_date: date, target_year: int) -> int:
        age = target_year - birth_date.year
        if age <= 0:
            return 22
        return sum_digits(age)

    @staticmethod
    def calculate_life_periods(birth_date: date) -> dict:
        periods = {}
        for age in [0, 7, 14, 21, 28, 35, 42, 49, 56, 63, 70]:
            target_year = birth_date.year + age
            periods[f"age_{age}"] = MatrixService.calculate_year_arcana(birth_date, target_year)
        return periods

    @staticmethod
    def calculate_year_forecast(birth_date: date, target_year: int) -> dict:
        return {
            "current": MatrixService.calculate_year_arcana(birth_date, target_year),
            "next": MatrixService.calculate_year_arcana(birth_date, target_year + 1),
            "next_next": MatrixService.calculate_year_arcana(birth_date, target_year + 2),
        }

    @staticmethod
    def calculate_chakras(matrix_data: "MatrixData | dict") -> dict:
        if isinstance(matrix_data, dict):
            matrix_data = MatrixData(**matrix_data)
        md = matrix_data

        sahasrara_key = sum_digits(md.portrait_zone + md.inner_h)
        ajna_key = sum_digits(md.talent_zone + md.inner_g)
        vishudha_key = sum_digits(md.inner_f + md.inner_i)
        anahata_key = sum_digits(md.comfort_zone + md.center)
        svadhisthana_key = sum_digits(md.top + md.talent_zone)
        muladhara_key = sum_digits(md.bottom + md.comfort_zone)

        all_nebo = [
            md.portrait_zone, md.talent_zone, md.inner_f,
            md.comfort_zone, md.left, md.top, md.bottom,
        ]
        all_zemlya = [
            md.inner_h, md.inner_g, md.inner_i,
            md.center, md.right, md.talent_zone, md.comfort_zone,
        ]
        organism_sky = sum_digits(sum(all_nebo))
        organism_earth = sum_digits(sum(all_zemlya))
        organism_key = sum_digits(organism_sky + organism_earth)

        return {
            "sahasrara_sky": md.portrait_zone,
            "sahasrara_earth": md.inner_h,
            "sahasrara_key": sahasrara_key,
            "ajna_sky": md.talent_zone,
            "ajna_earth": md.inner_g,
            "ajna_key": ajna_key,
            "vishudha_sky": md.inner_f,
            "vishudha_earth": md.inner_i,
            "vishudha_key": vishudha_key,
            "anahata_sky": md.comfort_zone,
            "anahata_earth": md.center,
            "anahata_key": anahata_key,
            "manipura_sky": md.left,
            "manipura_earth": md.right,
            "manipura_key": md.relationship_point,
            "svadhisthana_sky": md.top,
            "svadhisthana_earth": md.talent_zone,
            "svadhisthana_key": svadhisthana_key,
            "muladhara_sky": md.bottom,
            "muladhara_earth": md.comfort_zone,
            "muladhara_key": muladhara_key,
            "organism_sky": organism_sky,
            "organism_earth": organism_earth,
            "organism_key": organism_key,
        }

    @staticmethod
    def format_for_prompt(matrix_data: "MatrixData | dict") -> str:
        if isinstance(matrix_data, dict):
            matrix_data = MatrixData(**matrix_data)
        md = matrix_data
        day, month, year = parse_birth_date(md.birth_date)
        birth_date_obj = date(year, month, day)

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
            "",
            "== Жизненные периоды ==",
        ]
        periods = MatrixService.calculate_life_periods(birth_date_obj)
        for key, arcana_num in periods.items():
            age = key.replace("age_", "")
            lines.append(f"{age} лет: {ARCANA[arcana_num]['name']} ({arcana_num}) {ARCANA[arcana_num]['emoji']}")
        current_year = date.today().year
        forecast = MatrixService.calculate_year_forecast(birth_date_obj, current_year)
        lines.append("")
        lines.append("== Прогноз по годам ==")
        lines.append(f"Текущий год ({current_year}): {ARCANA[forecast['current']]['name']} ({forecast['current']}) {ARCANA[forecast['current']]['emoji']}")
        lines.append(f"Следующий год ({current_year + 1}): {ARCANA[forecast['next']]['name']} ({forecast['next']}) {ARCANA[forecast['next']]['emoji']}")
        lines.append(f"Через 2 года ({current_year + 2}): {ARCANA[forecast['next_next']]['name']} ({forecast['next_next']}) {ARCANA[forecast['next_next']]['emoji']}")
        lines.append("")
        lines.append("== Карта здоровья (чакры) ==")
        chakras = MatrixService.calculate_chakras(md)
        chakra_names = {
            "sahasrara": "Сахасрара (теменная)",
            "ajna": "Аджна (третий глаз)",
            "vishudha": "Вишудха (горловая)",
            "anahata": "Анахата (сердечная)",
            "manipura": "Манипура (солнечное сплетение)",
            "svadhisthana": "Свадхистхана (сакральная)",
            "muladhara": "Муладхара (корневая)",
        }
        for key_base, name in chakra_names.items():
            sky_num = chakras[f"{key_base}_sky"]
            earth_num = chakras[f"{key_base}_earth"]
            key_num = chakras[f"{key_base}_key"]
            lines.append(
                f"{name}: небо={ARCANA[sky_num]['name']} ({sky_num}), "
                f"земля={ARCANA[earth_num]['name']} ({earth_num}), "
                f"ключ={ARCANA[key_num]['name']} ({key_num})"
            )
        lines.append(
            f"Организм: небо={ARCANA[chakras['organism_sky']]['name']} ({chakras['organism_sky']}), "
            f"земля={ARCANA[chakras['organism_earth']]['name']} ({chakras['organism_earth']}), "
            f"ключ={ARCANA[chakras['organism_key']]['name']} ({chakras['organism_key']})"
        )
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
