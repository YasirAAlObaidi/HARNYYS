"""Markdown from the model becomes WhatsApp formatting."""

import pytest

from yyai.handlers.integrations.whatsapp_cloud.formatting import to_whatsapp


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("**Hi** there", "*Hi* there"),
        ("__Hi__ there", "*Hi* there"),
        ("# Menu", "*Menu*"),
        ("## Our **grinders** ##", "*Our grinders*"),
        ("[Shop](https://kahramandubai.com/x)", "Shop: https://kahramandubai.com/x"),
        ("[https://a.b](https://a.b)", "https://a.b"),
        ("- **F5**: AED 1,600\n- F64: AED 8,000", "- *F5*: AED 1,600\n- F64: AED 8,000"),
        ("مرحبا **قهوة** جيدة", "مرحبا *قهوة* جيدة"),
        ("# المطاحن\n- **مطحنة** 1600 درهم", "*المطاحن*\n- *مطحنة* 1600 درهم"),
        ("** spaced **", " *spaced* "),
        ("~~old~~ price", "~old~ price"),
        ("*already whatsapp* and _italic_", "*already whatsapp* and _italic_"),
        ("2 * 3 = 6", "2 * 3 = 6"),
        ("snake__case__name", "snake__case__name"),
        ("", ""),
    ],
)
def test_conversions(raw: str, expected: str) -> None:
    assert to_whatsapp(raw) == expected


@pytest.mark.parametrize(
    "raw",
    ["**open only", "close only**", "****", "** **", "**a** and **b", "**a **b** c**", "**قهوة", "x ** y ** z **"],
)
def test_never_leaves_stray_double_asterisks(raw: str) -> None:
    assert "**" not in to_whatsapp(raw)


def test_nested_bold_is_paired_left_to_right() -> None:
    assert to_whatsapp("**a **b** c**") == "*a* b *c*"


def test_bold_does_not_span_lines() -> None:
    assert to_whatsapp("**one\ntwo**") == "one\ntwo"
