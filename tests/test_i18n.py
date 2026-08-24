from datetime import date

import pytest

from ride_visuals.i18n import Translator, normalize_locale


def test_english_is_source_locale_and_formats_values():
    tr = Translator("en-US")
    assert tr.text("metric.heart_rate") == "Heart rate"
    assert tr.number(2689.5, 1) == "2,689.5"
    assert tr.date(date(2024, 8, 23)) == "Aug 23, 2024"


def test_portuguese_translation_and_locale_aware_number():
    tr = Translator("pt_BR")
    assert tr.text("metric.heart_rate") == "Frequência cardíaca"
    assert tr.number(2689.5, 1) == "2.689,5"
    assert tr.date(date(2024, 8, 23)) == "23/08/2024"


def test_unknown_locale_is_explicit():
    with pytest.raises(ValueError, match="Unsupported locale"):
        normalize_locale("de-DE")

