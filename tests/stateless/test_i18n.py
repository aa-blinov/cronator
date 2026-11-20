"""The i18n helper: literal keys, graceful degradation, interpolation."""

from app.services.i18n import translate


class TestTranslate:
    def test_english_is_identity(self):
        assert translate("Dashboard", "en") == "Dashboard"

    def test_unknown_locale_falls_back_to_english(self):
        assert translate("Dashboard", "xx") == "Dashboard"

    def test_russian_key_translates(self):
        assert translate("Dashboard", "ru") == "Дашборд"

    def test_missing_key_falls_back_to_the_literal(self):
        # A string not yet in the catalog renders in English, never errors.
        assert translate("Not in any catalog", "ru") == "Not in any catalog"

    def test_interpolation_applies_after_translation(self):
        rendered = translate("{count} script(s) total", "ru", count=3)
        assert rendered == "всего: 3"

    def test_bad_placeholder_does_not_raise(self):
        # A page must never fail to render over a translation.
        assert translate("{missing} literal", "ru") == "{missing} literal"
        assert translate("plain {oops}", "ru", other=1) == "plain {oops}"
