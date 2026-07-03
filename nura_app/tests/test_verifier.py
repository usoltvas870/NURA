import pytest

from core.services.verifier import ContentVerifier


class TestCheckLength:
    def test_enough_words_returns_none(self):
        text = "слово " * 60
        assert ContentVerifier.check_length(text, min_words=50) is None

    def test_too_few_words_returns_issue(self):
        text = "мало слов"
        issue = ContentVerifier.check_length(text, min_words=50, field_name="test")
        assert issue is not None
        assert "test" in issue
        assert "2 слов" in issue

    def test_zero_min_words(self):
        assert ContentVerifier.check_length("", min_words=0) is None


class TestCheckMaxLength:
    def test_within_limit_returns_none(self):
        assert ContentVerifier.check_max_length("короткий текст", max_words=10) is None

    def test_exceeds_limit_returns_issue(self):
        text = "слово " * 20
        issue = ContentVerifier.check_max_length(text, max_words=10, field_name="field")
        assert issue is not None
        assert "field" in issue

    def test_exact_max_ok(self):
        text = " ".join(str(i) for i in range(10))
        assert ContentVerifier.check_max_length(text, max_words=10) is None


class TestCheckBannedWords:
    def test_no_banned_words(self):
        assert ContentVerifier.check_banned_words("чистый текст") == []

    def test_detects_banned_word(self):
        issues = ContentVerifier.check_banned_words("это настоящее гадание на картах")
        assert len(issues) == 1
        assert "гадание" in issues[0]

    def test_detects_multiple_banned_words(self):
        issues = ContentVerifier.check_banned_words("магия и гадание и карма")
        assert len(issues) >= 2

    def test_case_insensitive(self):
        issues = ContentVerifier.check_banned_words("ГАДАНИЕ")
        assert len(issues) == 1


class TestCheckGenericPhrases:
    def test_no_generic_phrases(self):
        assert ContentVerifier.check_generic_phrases("конкретный совет") == []

    def test_detects_generic_phrase(self):
        issues = ContentVerifier.check_generic_phrases("просто будь собой и всё будет хорошо")
        assert len(issues) >= 2

    def test_returns_multiple(self):
        issues = ContentVerifier.check_generic_phrases("будь собой. слушай сердце.")
        assert len(issues) == 2


class TestCheckNotEmpty:
    def test_all_valid(self):
        d = {"a": "нормальное значение строки", "b": "тоже нормальное значение поля"}
        assert ContentVerifier.check_not_empty(d) == []

    def test_empty_string(self):
        issues = ContentVerifier.check_not_empty({"a": "", "b": "нормальное значение поля"})
        assert len(issues) == 1
        assert "a" in issues[0]

    def test_none_value(self):
        issues = ContentVerifier.check_not_empty({"a": None})
        assert len(issues) == 1
        assert "a" in issues[0]

    def test_too_short(self):
        issues = ContentVerifier.check_not_empty({"a": "аб"})
        assert len(issues) == 1


class TestVerifyReport:
    def test_good_report_passes(self):
        report = {k: "хороший содержательный текст " * 30 for k in [
            "main_archetype", "strengths", "shadow_side",
        ]}
        result = ContentVerifier.verify_report(report, min_words=10)
        assert result.passed
        assert result.issues == []

    def test_short_report_fails(self):
        report = {"main_archetype": "коротко", "strengths": "норма " * 20}
        result = ContentVerifier.verify_report(report, min_words=10)
        assert not result.passed
        assert any("main_archetype" in i for i in result.issues)

    def test_banned_words_fails(self):
        report = {"main_archetype": "гадание и магия " * 10 + "норма " * 10}
        result = ContentVerifier.verify_report(report, min_words=5)
        assert not result.passed
        assert any("гадание" in i for i in result.issues)

    def test_empty_report_fails(self):
        report = {"main_archetype": "", "strengths": None}
        result = ContentVerifier.verify_report(report)
        assert not result.passed

    def test_dashboard_insights_skipped(self):
        report = {
            "main_archetype": "норма " * 20,
            "dashboard_insights": None,
        }
        result = ContentVerifier.verify_report(report, min_words=10)
        assert result.passed


class TestVerifyText:
    def test_good_text_passes(self):
        text = "конкретный " * 20
        result = ContentVerifier.verify_text(text, min_words=10)
        assert result.passed

    def test_too_short_fails(self):
        result = ContentVerifier.verify_text("коротко", min_words=10)
        assert not result.passed

    def test_too_long_fails(self):
        text = "слово " * 20
        result = ContentVerifier.verify_text(text, min_words=5, max_words=10)
        assert not result.passed

    def test_banned_words_detected(self):
        result = ContentVerifier.verify_text("гадание", check_banned=True)
        assert not result.passed

    def test_tone_check(self):
        result = ContentVerifier.verify_text("будь собой", check_tone=True)
        assert not result.passed


class TestCheckNameInText:
    def test_name_present(self):
        assert ContentVerifier.check_name_in_text("Алексей, твоя карта дня", "Алексей") == []

    def test_name_absent(self):
        issues = ContentVerifier.check_name_in_text("твоя карта дня открыта", "Алексей")
        assert len(issues) == 1
        assert "Алексей" in issues[0]

    def test_case_insensitive(self):
        assert ContentVerifier.check_name_in_text("АЛЕКСЕЙ, смотри", "алексей") == []

    def test_empty_name_skipped(self):
        assert ContentVerifier.check_name_in_text("текст", "") == []

    def test_name_in_verify_text(self):
        result = ContentVerifier.verify_text("Алексей, слушай", min_words=1, user_name="Алексей")
        assert result.passed

    def test_name_missing_in_verify_text(self):
        result = ContentVerifier.verify_text("слушай, твоя карта", min_words=1, user_name="Алексей")
        assert not result.passed
        assert any("Алексей" in i for i in result.issues)
