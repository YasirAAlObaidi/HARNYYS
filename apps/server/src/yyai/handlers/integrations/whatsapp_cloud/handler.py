"""WhatsApp brand: Meta's WhatsApp Business Platform Cloud API. Fills the messaging job.

Webhook docs: developers.facebook.com/documentation/business-messaging/whatsapp/webhooks
Everything Meta-specific stays in this file.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx

from yyai.core.errors import IntegrationError, SignatureError
from yyai.core.types import InboundMessage, MediaRef, SendResult
from yyai.handlers.common.http import make_client, raise_for_status
from yyai.handlers.integrations.whatsapp_cloud.formatting import to_whatsapp

FREEFORM_WINDOW = timedelta(hours=24)
MAX_CAPTION = 1024  # Meta caps an image caption at 1024 characters.
MAX_TEXT = 4000  # Meta's limit is 4096 characters per text message.
_MEDIA_KINDS = {"image", "audio", "video", "document", "sticker"}


class WhatsAppCloud:
    def __init__(
        self,
        *,
        channel: str,
        phone_number_id: str,
        access_token: str,
        app_secret: str,
        verify_token: str,
        graph_version: str,
        images_dir: str | Path | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.channel = channel
        self._phone_number_id = phone_number_id
        self._app_secret = app_secret.encode()
        self._verify_token = verify_token
        self._images_dir = Path(images_dir) if images_dir else None
        self._media_ids: dict[str, str] = {}  # local file name -> Meta media id (valid ~30 days)
        self._client = client or make_client(
            base_url=f"https://graph.facebook.com/{graph_version}",
            headers={"Authorization": f"Bearer {access_token}"},
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    # --- inbound ---------------------------------------------------------

    def verify_subscription(self, params: Mapping[str, str]) -> str | None:
        if params.get("hub.mode") == "subscribe" and _same(params.get("hub.verify_token", ""), self._verify_token):
            return params.get("hub.challenge", "")
        return None

    def parse_webhook(self, headers: Mapping[str, str], body: bytes) -> list[InboundMessage]:
        self._check_signature(headers, body)
        payload = json.loads(body or b"{}")
        messages: list[InboundMessage] = []
        for entry in payload.get("entry", []):
            for change in entry.get("changes", []):
                value = change.get("value") or {}
                names = _contact_names(value.get("contacts") or [])
                for raw in value.get("messages") or []:
                    parsed = self._parse_message(raw, names)
                    if parsed:
                        messages.append(parsed)
                # Delivery and read receipts ("statuses") are ignored for now.
        return messages

    def _check_signature(self, headers: Mapping[str, str], body: bytes) -> None:
        received = _header(headers, "x-hub-signature-256")
        expected = "sha256=" + hmac.new(self._app_secret, body, hashlib.sha256).hexdigest()
        if not received or not _same(received, expected):
            raise SignatureError("WhatsApp webhook signature did not match")

    def _parse_message(self, raw: dict[str, Any], names: dict[str, str]) -> InboundMessage | None:
        # Meta is moving to business-scoped user IDs: `from` may be missing for users with usernames.
        sender = raw.get("from") or raw.get("from_user_id") or raw.get("user_id")
        source_id = raw.get("id")
        if not sender or not source_id:
            return None
        kind = raw.get("type", "")
        text = ""
        media: list[MediaRef] = []
        if kind == "text":
            text = (raw.get("text") or {}).get("body", "")
        elif kind == "interactive":
            reply = (raw.get("interactive") or {})
            chosen = reply.get("button_reply") or reply.get("list_reply") or {}
            text = chosen.get("title", "")
        elif kind == "button":
            text = (raw.get("button") or {}).get("text", "")
        elif kind in _MEDIA_KINDS:
            item = raw.get(kind) or {}
            caption = item.get("caption")
            media.append(
                MediaRef(kind=kind, provider_id=item.get("id", ""), mime_type=item.get("mime_type"), caption=caption)
            )
            text = caption or f"[{kind}]"
        else:
            text = f"[unsupported message type: {kind}]"
        timestamp = raw.get("timestamp")
        received_at = datetime.fromtimestamp(int(timestamp), UTC) if timestamp else datetime.now(UTC)
        return InboundMessage(
            channel=self.channel,
            source_id=source_id,
            sender_id=sender,
            sender_name=names.get(sender),
            text=text,
            received_at=received_at,
            media=media,
        )

    # --- outbound --------------------------------------------------------

    def freeform_allowed(self, last_inbound_at: datetime | None) -> bool:
        if last_inbound_at is None:
            return False
        return datetime.now(UTC) - last_inbound_at < FREEFORM_WINDOW

    async def send_text(self, to: str, text: str) -> SendResult:
        last_id = ""
        for chunk in _chunks(to_whatsapp(text), MAX_TEXT):
            last_id = await self._post_message(
                to, {"type": "text", "text": {"preview_url": False, "body": chunk}}
            )
        return SendResult(provider_message_id=last_id)

    async def send_image(self, to: str, image_url: str, caption: str) -> SendResult:
        """Send a picture. WhatsApp takes JPEG and PNG up to 5 MB. If we hold a local copy (images_dir plus its
        manifest.json), upload it to Meta and send by media id; otherwise fall back to the link."""
        caption = to_whatsapp(caption)[:MAX_CAPTION]
        path = self._local_file(image_url)
        if path is None:
            image: dict[str, Any] = {"link": image_url}
        else:
            image = {"id": self._media_ids.get(path.name) or await self._upload(path)}
        if caption:
            image["caption"] = caption
        try:
            message_id = await self._post_message(to, {"type": "image", "image": image})
        except IntegrationError:
            if path is None or "id" not in image or not self._media_ids.get(path.name):
                raise
            # A cached id may have expired or been revoked: upload again once and retry.
            self._media_ids.pop(path.name, None)
            image["id"] = await self._upload(path)
            message_id = await self._post_message(to, {"type": "image", "image": image})
        return SendResult(provider_message_id=message_id)

    def _local_file(self, image_url: str) -> Path | None:
        if self._images_dir is None:
            return None
        try:
            manifest = json.loads((self._images_dir / "manifest.json").read_text())
        except (OSError, ValueError):
            return None
        name = manifest.get(image_url)
        path = self._images_dir / name if name else None
        return path if path is not None and path.is_file() else None

    async def _upload(self, path: Path) -> str:
        mime = "image/png" if path.suffix.lower() == ".png" else "image/jpeg"
        try:
            response = await self._client.post(
                f"/{self._phone_number_id}/media",
                data={"messaging_product": "whatsapp", "type": mime},
                files={"file": (path.name, path.read_bytes(), mime)},
            )
        except httpx.HTTPError as exc:
            raise IntegrationError(f"WhatsApp unreachable: {exc}", retryable=True) from exc
        raise_for_status(response, "WhatsApp media upload")
        media_id = response.json().get("id")
        if not media_id:
            raise IntegrationError("WhatsApp media upload returned no id")
        self._media_ids[path.name] = media_id
        return media_id

    async def _post_message(self, to: str, body: dict[str, Any]) -> str:
        payload = {"messaging_product": "whatsapp", "recipient_type": "individual", "to": to, **body}
        try:
            response = await self._client.post(f"/{self._phone_number_id}/messages", json=payload)
        except httpx.HTTPError as exc:
            raise IntegrationError(f"WhatsApp unreachable: {exc}", retryable=True) from exc
        raise_for_status(response, "WhatsApp send")
        return (response.json().get("messages") or [{}])[0].get("id", "")


def _same(received: str, expected: str) -> bool:
    """Constant-time comparison. Works on bytes because compare_digest raises TypeError for non-ASCII str,
    which would turn a forged header or token into a server error instead of a refusal."""
    return hmac.compare_digest(received.encode(), expected.encode())


def _contact_names(contacts: list[dict[str, Any]]) -> dict[str, str]:
    names: dict[str, str] = {}
    for contact in contacts:
        name = (contact.get("profile") or {}).get("name")
        for key in ("wa_id", "user_id", "from_user_id"):
            if contact.get(key) and name:
                names[contact[key]] = name
    return names


def _header(headers: Mapping[str, str], name: str) -> str | None:
    for key, value in headers.items():
        if key.lower() == name:
            return value
    return None


def _chunks(text: str, size: int) -> list[str]:
    if len(text) <= size:
        return [text]
    parts, current = [], ""
    for paragraph in text.split("\n"):
        if len(current) + len(paragraph) + 1 > size and current:
            parts.append(current)
            current = ""
        current = f"{current}\n{paragraph}" if current else paragraph
        while len(current) > size:
            parts.append(current[:size])
            current = current[size:]
    if current:
        parts.append(current)
    return parts
