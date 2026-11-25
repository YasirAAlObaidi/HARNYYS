"""normalize_for_search: the one function that makes Arabic and English comparable for fuzzy search."""

import pytest

from yyai.core.text import normalize_for_search

FATHA = "َ"
DAMMA = "ُ"
KASRA = "ِ"
SHADDA = "ّ"
SUKUN = "ْ"
TANWEEN_FATH = "ً"
TATWEEL = "ـ"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("٠١٢٣٤٥٦٧٨٩", "0123456789"),  # Arabic-Indic digits
        ("۰۱۲۳۴۵۶۷۸۹", "0123456789"),  # Persian digits
        ("قارورة ٢٠ لتر", "قاروره 20 لتر"),  # taa marbuta folds too
        ("250 جم", "250 جم"),
    ],
)
def test_eastern_arabic_digits_become_ascii(raw: str, expected: str) -> None:
    assert normalize_for_search(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("أحمد", "احمد"),  # alef with hamza above
        ("إسبريسو", "اسبريسو"),  # alef with hamza below
        ("آلة", "اله"),  # alef with madda, and taa marbuta
        ("ٱكتاب", "اكتاب"),  # alef wasla
        ("ماكينة", "ماكينه"),  # taa marbuta -> haa
        ("قهوة", "قهوه"),
        ("مصطفى", "مصطفي"),  # alef maqsura -> yaa
        ("مؤسسة", "موسسه"),  # waw with hamza
        ("رئيس", "رييس"),  # yaa with hamza
    ],
)
def test_letter_variants_fold_together(raw: str, expected: str) -> None:
    assert normalize_for_search(raw) == expected


def test_alef_and_taa_marbuta_variants_of_the_same_word_match() -> None:
    assert (
        normalize_for_search("اثيوبية") == normalize_for_search("إثيوبيّة") == normalize_for_search("أثيوبيه")
    )


def test_diacritics_are_removed() -> None:
    word = f"ق{FATHA}ه{SUKUN}و{FATHA}ة{TANWEEN_FATH}"
    assert normalize_for_search(word) == "قهوه"
    assert normalize_for_search(f"م{SHADDA}{DAMMA}ح{KASRA}م{SHADDA}{FATHA}د") == "محمد"


def test_tatweel_is_removed() -> None:
    assert normalize_for_search(f"قهـ{TATWEEL}{TATWEEL}ـوة") == "قهوه"


def test_latin_text_is_lowercased() -> None:
    assert normalize_for_search("Ethiopia YIRGACHEFFE Beans") == "ethiopia yirgacheffe beans"


def test_whitespace_is_collapsed_and_trimmed() -> None:
    assert normalize_for_search("  Moka \t Pot \n 6   Cups  ") == "moka pot 6 cups"


def test_arabic_decimal_separators_become_ascii() -> None:
    assert normalize_for_search("٢٫٥ لتر") == "2.5 لتر"
    assert normalize_for_search("١٬٠٠٠") == "1,000"


def test_mixed_arabic_and_english_in_one_string() -> None:
    assert normalize_for_search("قهوة كينية AA حبوب ٢٥٠ جم") == "قهوه كينيه aa حبوب 250 جم"


@pytest.mark.parametrize("raw", ["", "   ", "\n\t"])
def test_empty_input_stays_empty(raw: str) -> None:
    assert normalize_for_search(raw) == ""


def test_is_idempotent() -> None:
    once = normalize_for_search("إسبريسو ٢٥٠ جم  Machine")
    assert normalize_for_search(once) == once
