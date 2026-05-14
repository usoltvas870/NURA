import pytest

from core.schemas import MatrixData
from core.services.matrix import ARCANA, MatrixService


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
