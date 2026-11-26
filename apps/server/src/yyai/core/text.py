"""Text helpers shared by every layer. Pure functions, no I/O."""

import re
import unicodedata

_ARABIC_DIACRITICS = re.compile(r"[ؐ-ًؚ-ٰٟۖ-ۭ]")
_TATWEEL = "ـ"
_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")
_LETTERS = str.maketrans(
    {
        "أ": "ا",
        "إ": "ا",
        "آ": "ا",
        "ٱ": "ا",
        "ى": "ي",
        "ة": "ه",
        "ؤ": "و",
        "ئ": "ي",
        "٫": ".",
        "٬": ",",
    }
)
_SPACES = re.compile(r"\s+")


def western_digits(text: str) -> str:
    """Turn Eastern Arabic (٠-٩) and Persian (۰-۹) digits into 0-9. Everything else is left as it is."""
    return text.translate(_DIGITS)


def phone_digits(text: str) -> str | None:
    """The digits of `text` when it looks like (part of) a phone number, such as "+971 50 123" or "٠٥٠١٢٣".

    Returns None for anything else, including fewer than three digits.
    """
    compact = re.sub(r"[\s+\-().]", "", western_digits(text))
    return compact if len(compact) >= 3 and compact.isascii() and compact.isdigit() else None


def normalize_for_search(text: str) -> str:
    """Make Arabic and English text comparable for fuzzy search.

    Turns Eastern Arabic digits into 0-9, folds alef/yaa/taa-marbuta variants,
    removes diacritics and tatweel, lowercases Latin text and collapses spaces.
    """
    text = unicodedata.normalize("NFKC", text)
    text = text.translate(_DIGITS)
    text = _ARABIC_DIACRITICS.sub("", text).replace(_TATWEEL, "")
    text = text.translate(_LETTERS)
    return _SPACES.sub(" ", text.lower()).strip()
