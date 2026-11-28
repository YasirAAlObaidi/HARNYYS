"""Variants: grouping under a base product, choosing an option, and the pictures a reply sends."""

from __future__ import annotations

import json
from decimal import Decimal

import httpx
import pytest
import respx

from yyai.core.types import CatalogueItem, CatalogueMatch, PresentedProduct
from yyai.core.variants import base_key, chosen_variants, group_matches, variant_label
from yyai.handlers.integrations.webchat.handler import WebChat
from yyai.handlers.integrations.whatsapp_cloud.handler import MAX_CAPTION, WhatsAppCloud
from yyai.workflows.agent.images import caption, pick_images


def make(code: str, name: str, **attrs: object) -> CatalogueItem:
    return CatalogueItem(code=code, name_en=name, name_ar=name, attributes=attrs, price=Decimal(100))


F5 = [
    make("f5-b", "F5 Grinder (Black)", variant_of="f5", color="Black"),
    make("f5-w", "F5 Grinder (White)", variant_of="f5", color="White"),
    make("f5-r", "F5 Grinder (Red)", variant_of="f5", color="Red"),
]


# --- grouping ---------------------------------------------------------------------------------------------------


def test_variants_group_under_one_base_product_without_option_names() -> None:
    other = make("hand", "Hand Grinder (Pocket Edition)")  # brackets but not a variant: name stays whole
    groups = group_matches([CatalogueMatch(item=i, score=0.9) for i in [*F5[:2], other, F5[2]]])
    assert [g.base_key for g in groups] == ["f5", "hand"]
    assert groups[0].name_en == "F5 Grinder"
    assert [i.code for i in groups[0].items] == ["f5-b", "f5-w", "f5-r"]
    assert groups[0].has_variants
    assert groups[1].name_en == "Hand Grinder (Pocket Edition)"
    assert not groups[1].has_variants


def test_base_code_beats_variant_of_and_label_can_be_explicit() -> None:
    item = make("x-1", "Thing", base_code="thing", variant_of="other", variant_label="Large")
    assert base_key(item) == "thing"
    assert variant_label(item) == "Large"
    assert variant_label(F5[0]) == "Black"
    assert variant_label(make("g", "Machine (Black, 2 Groups)", variant_of="m")) == "Black, 2 Groups"
    assert variant_label(make("plain", "Plain")) is None


def test_chosen_variants_match_the_option_in_the_customers_words() -> None:
    assert [i.code for i in chosen_variants(F5, "the F5 grinder in red")] == ["f5-r"]
    assert chosen_variants(F5, "the F5 grinder") == []
    lollo = [make("l2", "Lollo (Black, 2 Groups)", variant_of="l"), make("l3", "Lollo (Black, 3 Groups)", variant_of="l")]
    assert [i.code for i in chosen_variants(lollo, "lollo black 3 groups")] == ["l3"]
    assert len(chosen_variants(lollo, "lollo black")) == 2


def test_chosen_variants_understand_an_arabic_option() -> None:
    items = [
        CatalogueItem(code="a", name_en="F5 (Black)", name_ar="مطحنة (أسود)", attributes={"variant_of": "f5"}),
        CatalogueItem(code="b", name_en="F5 (Red)", name_ar="مطحنة (أحمر)", attributes={"variant_of": "f5"}),
    ]
    assert [i.code for i in chosen_variants(items, "ابي المطحنة الاحمر")] == ["b"]


# --- picking pictures ---------------------------------------------------------------------------------------------


def shown(n: int, *, specific: bool = False, url: str | None = "https://img.test/{n}.jpg") -> list[PresentedProduct]:
    return [
        PresentedProduct(
            key=f"k{i}", name=f"Product {i}", price=Decimal(1600), image_url=url.format(n=i) if url else None, specific=specific
        )
        for i in range(n)
    ]


def test_at_most_max_images_are_picked_in_order() -> None:
    images = pick_images(shown(5), 3)
    assert [i.url for i in images] == [f"https://img.test/{n}.jpg" for n in range(3)]
    assert pick_images(shown(5), 0) == []


def test_products_named_by_the_customer_win_over_search_results() -> None:
    presented = [*shown(3), PresentedProduct(key="z", name="Chosen", image_url="https://img.test/z.png", specific=True)]
    assert [i.url for i in pick_images(presented, 3)] == ["https://img.test/z.png"]


def test_items_without_a_usable_picture_are_skipped() -> None:
    presented = [
        PresentedProduct(key="a", name="A", image_url=None),
        PresentedProduct(key="b", name="B", image_url="https://img.test/b.webp"),
        PresentedProduct(key="c", name="C", image_url="https://img.test/c.gif"),
        PresentedProduct(key="d", name="D", image_url="https://img.test/d.JPG"),
    ]
    assert [i.url for i in pick_images(presented, 3)] == ["https://img.test/d.JPG"]


def test_caption_is_whatsapp_formatted_with_the_price() -> None:
    plain = PresentedProduct(key="a", name="F5 *Grinder*", price=Decimal(1600), currency="AED")
    assert caption(plain) == "*F5 Grinder*\nAED 1,600"
    ranged = PresentedProduct(key="a", name="F5", price=Decimal("1599.5"), price_from=True, currency="AED")
    assert caption(ranged) == "*F5*\nfrom AED 1,599.50"
    assert caption(PresentedProduct(key="a", name="F5")) == "*F5*"


# --- sending an image ---------------------------------------------------------------------------------------------

MESSAGES_URL = "https://graph.facebook.com/v23.0/109/messages"


@pytest.fixture
def wa() -> WhatsAppCloud:
    return WhatsAppCloud(
        channel="whatsapp", phone_number_id="109", access_token="tok", app_secret="s", verify_token="v", graph_version="v23.0"
    )


async def test_send_image_posts_a_link_with_a_whatsapp_formatted_caption(wa: WhatsAppCloud) -> None:
    with respx.mock(assert_all_mocked=True) as router:
        route = router.post(MESSAGES_URL).mock(return_value=httpx.Response(200, json={"messages": [{"id": "wamid.I1"}]}))
        result = await wa.send_image("971501234567", "https://img.test/a.jpg", "**F5**\nAED 1,600")
    assert result.provider_message_id == "wamid.I1"
    assert json.loads(route.calls[0].request.content) == {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": "971501234567",
        "type": "image",
        "image": {"link": "https://img.test/a.jpg", "caption": "*F5*\nAED 1,600"},
    }


async def test_send_image_cuts_the_caption_and_omits_an_empty_one(wa: WhatsAppCloud) -> None:
    with respx.mock(assert_all_mocked=True) as router:
        route = router.post(MESSAGES_URL).mock(return_value=httpx.Response(200, json={"messages": [{"id": "x"}]}))
        await wa.send_image("1", "https://img.test/a.jpg", "ب" * 3000)
        await wa.send_image("1", "https://img.test/a.jpg", "")
    assert len(json.loads(route.calls[0].request.content)["image"]["caption"]) == MAX_CAPTION
    assert "caption" not in json.loads(route.calls[1].request.content)["image"]


async def test_send_text_is_converted_to_whatsapp_formatting(wa: WhatsAppCloud) -> None:
    with respx.mock(assert_all_mocked=True) as router:
        route = router.post(MESSAGES_URL).mock(return_value=httpx.Response(200, json={"messages": [{"id": "x"}]}))
        await wa.send_text("1", "## Grinders\n- **F5**: AED 1,600")
    assert json.loads(route.calls[0].request.content)["text"]["body"] == "*Grinders*\n- *F5*: AED 1,600"


async def test_webchat_send_image_is_a_no_op_with_an_id() -> None:
    result = await WebChat(channel="webchat").send_image("u", "https://img.test/a.jpg", "cap")
    assert result.provider_message_id.startswith("webchat-")


# --- local image upload ---------------------------------------------------------------------------------------------

MEDIA_URL = "https://graph.facebook.com/v23.0/109/media"


@pytest.fixture
def wa_local(tmp_path) -> WhatsAppCloud:
    (tmp_path / "a.jpg").write_bytes(b"\xff\xd8jpegbytes")
    (tmp_path / "manifest.json").write_text(json.dumps({"https://img.test/a.jpg": "a.jpg"}))
    return WhatsAppCloud(
        channel="whatsapp", phone_number_id="109", access_token="tok", app_secret="s", verify_token="v",
        graph_version="v23.0", images_dir=tmp_path,
    )


async def test_send_image_uploads_the_local_file_once_and_sends_by_media_id(wa_local: WhatsAppCloud) -> None:
    with respx.mock(assert_all_mocked=True) as router:
        media = router.post(MEDIA_URL).mock(return_value=httpx.Response(200, json={"id": "M1"}))
        send = router.post(MESSAGES_URL).mock(return_value=httpx.Response(200, json={"messages": [{"id": "w1"}]}))
        await wa_local.send_image("1", "https://img.test/a.jpg", "*F5*")
        await wa_local.send_image("2", "https://img.test/a.jpg", "")
    assert media.call_count == 1
    body = media.calls[0].request.content
    assert b'name="messaging_product"' in body and b"whatsapp" in body and b"image/jpeg" in body and b"jpegbytes" in body
    assert json.loads(send.calls[0].request.content)["image"] == {"id": "M1", "caption": "*F5*"}
    assert json.loads(send.calls[1].request.content)["image"] == {"id": "M1"}


async def test_send_image_reuploads_once_when_the_cached_id_is_rejected(wa_local: WhatsAppCloud) -> None:
    with respx.mock(assert_all_mocked=True) as router:
        media = router.post(MEDIA_URL).mock(
            side_effect=[httpx.Response(200, json={"id": "M1"}), httpx.Response(200, json={"id": "M2"})]
        )
        send = router.post(MESSAGES_URL).mock(
            side_effect=[
                httpx.Response(200, json={"messages": [{"id": "w1"}]}),
                httpx.Response(400, json={"error": {"message": "media expired"}}),
                httpx.Response(200, json={"messages": [{"id": "w2"}]}),
            ]
        )
        await wa_local.send_image("1", "https://img.test/a.jpg", "")
        result = await wa_local.send_image("1", "https://img.test/a.jpg", "")
    assert result.provider_message_id == "w2"
    assert media.call_count == 2
    assert json.loads(send.calls[2].request.content)["image"] == {"id": "M2"}


async def test_send_image_falls_back_to_the_link_without_a_local_file(wa_local: WhatsAppCloud) -> None:
    with respx.mock(assert_all_mocked=True) as router:
        send = router.post(MESSAGES_URL).mock(return_value=httpx.Response(200, json={"messages": [{"id": "w"}]}))
        await wa_local.send_image("1", "https://img.test/other.jpg", "")
    assert json.loads(send.calls[0].request.content)["image"] == {"link": "https://img.test/other.jpg"}


def test_search_only_products_need_to_be_named_in_the_reply() -> None:
    greeting = [
        PresentedProduct(key="a", name="Fiorenzato F5 Coffee Grinder", image_url="https://img.test/a.jpg"),
        PresentedProduct(key="b", name="Brazil Lot 200", image_url="https://img.test/b.jpg"),
    ]
    assert pick_images(greeting, 3, "Hi there! How can I help you today?") == []
    named = pick_images(greeting, 3, "We have the Fiorenzato F5 and Brazil Lot 200.")
    assert [i.url for i in named] == ["https://img.test/a.jpg", "https://img.test/b.jpg"]
    only_f4 = [PresentedProduct(key="c", name="Fiorenzato F4 A Coffee Grinder", image_url="https://img.test/c.jpg")]
    assert pick_images(only_f4, 3, "The Fiorenzato F5 is great") == []  # model numbers must match
    asked = [PresentedProduct(key="d", name="Brazil Lot 200", image_url="https://img.test/d.jpg", specific=True)]
    assert len(pick_images(asked, 3, "Which colour do you want?")) == 1  # the customer named it
    arabic = [
        PresentedProduct(key="e", name="Brazil Lot 200", name_ar="قهوة خضراء برازيلية – لوت 200", image_url="https://img.test/e.jpg")
    ]
    assert len(pick_images(arabic, 3, "عندنا برازيلية لوت 200 متوفرة")) == 1


def test_colour_variants_are_grouped_from_names_when_the_inventory_gives_no_base_code() -> None:
    from yyai.services.catalogue import with_derived_variants

    def make(code: str, name: str) -> CatalogueItem:
        return CatalogueItem(code=code, name_en=name, category="Grinders")

    items = [
        make("f5-b", "Fiorenzato F5 Coffee Grinder (Black)"),
        make("f5-r", "Fiorenzato F5 Coffee Grinder (Red)"),
        make("drog-b", "Fiorenzato F5 Drog Coffee Grinder (Black)"),
        make("aud-1", "Audrey (Grey, 1 Group)"),
        make("aud-2", "Audrey (Grey, 2 Groups)"),
        make("solo", "Solo Grinder (Black)"),
    ]
    grouped = {i.code: i.attributes.get("base_code") for i in with_derived_variants(items)}
    assert grouped["f5-b"] == grouped["f5-r"] == "fiorenzato-f5-coffee-grinder"
    assert grouped["drog-b"] is None  # a different product that happens to come in black
    assert grouped["aud-1"] is None and grouped["aud-2"] is None
    assert grouped["solo"] is None  # one colour is not a variant group


def test_colour_words_are_left_out_of_the_product_lookup() -> None:
    from yyai.core.text import normalize_for_search
    from yyai.services.catalogue import strip_colours

    assert strip_colours(normalize_for_search("Fiorenzato F5 black")) == "fiorenzato f5"
    assert strip_colours(normalize_for_search("مطحنة F5 الأسود")) == normalize_for_search("مطحنة F5")
    assert strip_colours(normalize_for_search("black")) == "black"  # only a colour: keep it
