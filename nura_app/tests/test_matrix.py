import pytest
from datetime import date

from core.schemas import MatrixData
from core.services.matrix import ARCANA, MatrixService, sum_digits


class TestCalculate:
    def test_returns_matrix_data(self):
        result = MatrixService.calculate("01.01.2000")
        assert isinstance(result, MatrixData)

    def test_22_arcana(self):
        assert len(ARCANA) == 22
        for i in range(1, 23):
            assert i in ARCANA
            assert "name" in ARCANA[i]

    def test_sample_date_01_01_2000(self):
        result = MatrixService.calculate("01.01.2000")
        assert result.center == 8
        assert result.top == 1
        assert result.bottom == 4
        assert result.left == 1
        assert result.right == 2
        assert result.arcana_names["center"] == "Сила"

    def test_sample_date_15_06_1998(self):
        result = MatrixService.calculate("15.06.1998")
        assert result.center == 6
        assert result.top == 6
        assert result.bottom == 3
        assert result.left == 15
        assert result.right == 9
        assert result.arcana_names["center"] == "Влюблённые"

    def test_sample_date_31_12_2024(self):
        result = MatrixService.calculate("31.12.2024")
        assert result.center == 3
        assert result.top == 12
        assert result.bottom == 6
        assert result.left == 4
        assert result.right == 8
        assert result.arcana_names["center"] == "Императрица"

    def test_invalid_date(self):
        with pytest.raises((ValueError, IndexError)):
            MatrixService.calculate("")
        with pytest.raises((ValueError, IndexError)):
            MatrixService.calculate("not-a-date")


class TestArchetypeName:
    def test_returns_correct_name(self):
        assert MatrixService.get_archetype_name(3) == "Императрица"
        assert MatrixService.get_archetype_name(1) == "Маг"
        assert MatrixService.get_archetype_name(22) == "Шут"

    def test_invalid_number(self):
        assert MatrixService.get_archetype_name(99) == "Неизвестный"
        assert MatrixService.get_archetype_name(0) == "Неизвестный"
        assert MatrixService.get_archetype_name(-1) == "Неизвестный"


class TestFormatForPrompt:
    def test_returns_string(self):
        result = MatrixService.calculate("01.01.2000")
        text = MatrixService.format_for_prompt(result)
        assert isinstance(text, str)
        assert len(text) > 0
        assert "Дата рождения: 01.01.2000" in text

    def test_accepts_dict(self):
        data = MatrixService.calculate("01.01.2000").model_dump()
        text = MatrixService.format_for_prompt(data)
        assert isinstance(text, str)
        assert len(text) > 0


class TestSumDigits:
    """Edge cases для sum_digits — рекурсивное суммирование цифр до 1-22."""

    def test_zero_returns_zero(self):
        """0 → 0 (сразу <= 22, без изменений)."""
        assert sum_digits(0) == 0

    def test_22_unchanged(self):
        """22 → 22 (граничное значение, не меняется)."""
        assert sum_digits(22) == 22

    def test_23_reduces_to_5(self):
        """23 → 2+3=5."""
        assert sum_digits(23) == 5

    def test_99_reduces_to_18(self):
        """99 → 9+9=18 (18 ≤ 22, останов)."""
        assert sum_digits(99) == 18

    def test_1999_reduces_to_10(self):
        """1999 → 1+9+9+9=28 → 2+8=10."""
        assert sum_digits(1999) == 10

    def test_large_number_chain(self):
        """9999 → 36 → 9."""
        assert sum_digits(9999) == 9

    def test_negative_passes_through(self):
        """Отрицательные числа не проходят редукцию (< 22)."""
        assert sum_digits(-123) == -123


class TestCalculateEdgeCases:
    """Граничные даты для calculate: високосный год, древние даты."""

    def test_leap_year_29_02_2024(self):
        """Високосный год 29.02.2024 — корректный расчёт."""
        result = MatrixService.calculate("29.02.2024")
        assert isinstance(result, MatrixData)
        # Проверяем базовую структуру
        assert result.center == 6
        assert result.top == 2
        assert result.left == 11
        assert result.right == 8
        assert result.arcana_names["center"] == "Влюблённые"

    def test_year_0001_01_01(self):
        """01.01.0001 — минимальная дата."""
        result = MatrixService.calculate("01.01.0001")
        assert isinstance(result, MatrixData)
        assert result.center == 6
        assert result.top == 1
        assert result.bottom == 3
        assert result.left == 1
        assert result.right == 1

    def test_year_9999_12_31(self):
        """31.12.9999 — максимальная дата без ошибок."""
        result = MatrixService.calculate("31.12.9999")
        assert isinstance(result, MatrixData)
        # 31 → 4, 12 → 3, 9999 → 36 → 9, D=4+3+9=16→16, E=4+3+9+16=32→5
        assert result.center == 5
        assert result.arcana_names["center"] == "Иерофант"

    def test_single_digit_day_month(self):
        """Дата с однозначным днём и месяцем без ведущего нуля."""
        result = MatrixService.calculate("5.6.2020")
        assert isinstance(result, MatrixData)


class TestFormatForPromptCompleteness:
    """format_for_prompt содержит все ключевые секции."""

    def test_contains_main_positions(self):
        text = MatrixService.format_for_prompt(MatrixService.calculate("01.01.2000"))
        assert "== Основные позиции ==" in text
        assert "Центр" in text
        assert "Верх" in text
        assert "Низ" in text
        assert "Лево" in text
        assert "Право" in text

    def test_contains_zones(self):
        text = MatrixService.format_for_prompt(MatrixService.calculate("01.01.2000"))
        assert "== Зоны ==" in text
        assert "Зона талантов" in text
        assert "Зона комфорта" in text
        assert "Портретная зона" in text

    def test_contains_karmic_tail(self):
        text = MatrixService.format_for_prompt(MatrixService.calculate("01.01.2000"))
        assert "== Кармический хвост ==" in text
        assert "Причина" in text
        assert "Следствие" in text
        assert "Урок" in text

    def test_contains_inner_points(self):
        text = MatrixService.format_for_prompt(MatrixService.calculate("01.01.2000"))
        assert "== Внутренние точки ==" in text
        assert "Кармический дар" in text
        assert "Линия отца" in text
        assert "Денежный канал" in text
        assert "Линия матери" in text

    def test_contains_lines(self):
        text = MatrixService.format_for_prompt(MatrixService.calculate("01.01.2000"))
        assert "== Линии ==" in text
        assert "Линия неба" in text
        assert "Линия земли" in text
        assert "Линия отношений" in text
        assert "Линия денег" in text
        assert "Точка отношений" in text

    def test_contains_life_periods(self):
        """Секция «Жизненные периоды»."""
        text = MatrixService.format_for_prompt(MatrixService.calculate("01.01.2000"))
        assert "== Жизненные периоды ==" in text
        for age in ["0", "7", "14", "21", "28", "35", "42", "49", "56", "63", "70"]:
            assert f"{age} лет:" in text

    def test_contains_year_forecast(self):
        """Секция «Прогноз по годам»."""
        text = MatrixService.format_for_prompt(MatrixService.calculate("01.01.2000"))
        assert "== Прогноз по годам ==" in text
        assert "Текущий год" in text
        assert "Следующий год" in text
        assert "Через 2 года" in text

    def test_contains_health_map(self):
        """Секция «Карта здоровья (чакры)»."""
        text = MatrixService.format_for_prompt(MatrixService.calculate("01.01.2000"))
        assert "== Карта здоровья (чакры) ==" in text
        for chakra in ["Сахасрара", "Аджна", "Вишудха", "Анахата", "Манипура", "Свадхистхана", "Муладхара"]:
            assert chakra in text

    def test_accepts_dict_returns_same_sections(self):
        """При передаче dict format_for_prompt возвращает те же секции."""
        data = MatrixService.calculate("01.01.2000").model_dump()
        text = MatrixService.format_for_prompt(data)
        assert "== Основные позиции ==" in text
        assert "== Жизненные периоды ==" in text
        assert "== Прогноз по годам ==" in text
        assert "== Карта здоровья (чакры) ==" in text


class TestCalculateYearArcana:
    """calculate_year_arcana для разных лет."""

    def test_current_year(self):
        """Год рождения → возраст 0 → 22 (Шут)."""
        from datetime import date
        result = MatrixService.calculate_year_arcana(date(2000, 1, 1), 2000)
        assert result == 22
        assert MatrixService.get_archetype_name(result) == "Шут"

    def test_next_year(self):
        """На 1 год старше → 1 (Маг)."""
        from datetime import date
        result = MatrixService.calculate_year_arcana(date(2000, 1, 1), 2001)
        assert result == 1

    def test_future_year(self):
        """24 года спустя → 6."""
        from datetime import date
        result = MatrixService.calculate_year_arcana(date(2000, 1, 1), 2024)
        assert result == 6

    def test_before_birth(self):
        """Год до рождения → возраст ≤ 0 → 22."""
        from datetime import date
        result = MatrixService.calculate_year_arcana(date(2000, 1, 1), 1999)
        assert result == 22

    def test_22_years_later(self):
        """Ровно 22 года → 22 (22 свёрнуто в 22)."""
        from datetime import date
        result = MatrixService.calculate_year_arcana(date(2000, 1, 1), 2022)
        assert result == 22

    def test_23_years_later(self):
        """23 года → 2+3=5."""
        from datetime import date
        result = MatrixService.calculate_year_arcana(date(2000, 1, 1), 2023)
        assert result == 5


class TestCalculateLifePeriods:
    """calculate_life_periods — проверка структуры."""

    def test_returns_dict_with_expected_keys(self):
        """Ключи age_0 … age_70 с шагом 7."""
        periods = MatrixService.calculate_life_periods(date(2000, 1, 1))
        expected_keys = [f"age_{age}" for age in range(0, 71, 7)]
        assert list(periods.keys()) == expected_keys

    def test_all_values_in_1_22_range(self):
        """Все значения арканов в диапазоне 1-22."""
        periods = MatrixService.calculate_life_periods(date(2000, 1, 1))
        for key, val in periods.items():
            assert 1 <= val <= 22, f"{key} = {val} вне диапазона 1-22"

    def test_known_values_2000_birth(self):
        """Проверка конкретных значений для 01.01.2000."""
        periods = MatrixService.calculate_life_periods(date(2000, 1, 1))
        assert periods["age_0"] == 22  # Шут
        assert periods["age_7"] == 7   # Колесница
        assert periods["age_21"] == 21  # Мир


class TestCalculateYearForecast:
    """calculate_year_forecast — структура ответа."""

    def test_returns_dict_with_three_keys(self):
        forecast = MatrixService.calculate_year_forecast(date(2000, 1, 1), 2024)
        assert isinstance(forecast, dict)
        assert list(forecast.keys()) == ["current", "next", "next_next"]

    def test_all_values_in_1_22_range(self):
        forecast = MatrixService.calculate_year_forecast(date(2000, 1, 1), 2024)
        for key, val in forecast.items():
            assert 1 <= val <= 22, f"{key} = {val} вне диапазона 1-22"


class TestGetArchetypeNameEdgeCases:
    """Дополнительные граничные случаи get_archetype_name."""

    def test_23_returns_unknown(self):
        """23 вне ARCANA → 'Неизвестный'."""
        assert MatrixService.get_archetype_name(23) == "Неизвестный"

    def test_all_1_to_22_valid(self):
        """Все числа 1-22 возвращают имя (не пустое и не 'Неизвестный')."""
        for i in range(1, 23):
            name = MatrixService.get_archetype_name(i)
            assert isinstance(name, str) and len(name) > 0
            assert name != "Неизвестный", f"Аркан {i} вернул 'Неизвестный'"


class TestARCANA:
    """Полнота словаря ARCANA."""

    def test_22_keys_exist(self):
        """Ровно 22 ключа 1..22."""
        assert len(ARCANA) == 22
        for i in range(1, 23):
            assert i in ARCANA, f"Ключ {i} отсутствует в ARCANA"

    def test_each_arcana_has_required_fields(self):
        """Каждый аркан содержит name, emoji, symbol, key, phrase."""
        required = {"name", "emoji", "symbol", "key", "phrase", "interpretation", "advice", "affirmation"}
        for i, data in ARCANA.items():
            missing = required - set(data.keys())
            assert not missing, f"Аркан {i} не имеет полей: {missing}"

