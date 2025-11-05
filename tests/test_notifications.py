import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.append(str(Path(__file__).resolve().parents[1]))

from models import Token, Transaction
from notifications import MultiTelegramHandler, TelegramConfig, TelegramDestination


class DummyResponse:
    def __init__(self, status: int, payload: dict):
        self.status = status
        self._payload = payload

    async def json(self):
        return self._payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


class DummySession:
    def __init__(self, response_factory):
        self.response_factory = response_factory
        self.requests = []
        self.closed = False

    def post(self, url, json):
        self.requests.append((url, json))
        return self.response_factory(url, json)

    async def close(self):
        self.closed = True


def create_sample_transaction(**overrides) -> Transaction:
    defaults = {
        "tx_type": "payment",
        "value": 1.23456789,
        "fee": 0.001,
        "from_address": "9fromAddress",
        "to_address": "9toAddress",
        "tokens": [
            Token(
                token_id="token123",
                amount=123456,
                name="Test Token",
                decimals=4,
            )
        ],
        "tx_id": "tx123",
        "block": 1234,
        "timestamp": datetime.now(timezone.utc),
        "status": "Confirmed",
    }
    defaults.update(overrides)
    return Transaction(**defaults)


def test_telegram_destination_formats_chat_id():
    dest = TelegramDestination(chat_id="12345")
    assert dest.chat_id == "-10012345"


def test_telegram_destination_preserves_existing_prefix():
    dest = TelegramDestination(chat_id="-10099999")
    assert dest.chat_id == "-10099999"


def test_get_destinations_for_address_prefers_specific_configs():
    address = "9ABCDEFGHIJKLMNOPQRSTUVWXYZ1234567890"
    config = TelegramConfig(
        destinations=[TelegramDestination(chat_id="-10022222")]
    )
    handler = MultiTelegramHandler(
        bot_token="token",
        address_configs={address: config},
        default_chat_id="-10011111",
    )

    specific = handler.get_destinations_for_address(address)
    assert len(specific) == 1
    assert specific[0].chat_id == "-10022222"

    fallback = handler.get_destinations_for_address("unknown")
    assert len(fallback) == 1
    assert fallback[0].chat_id == "-10011111"


@pytest.mark.asyncio
async def test_handle_transaction_sends_messages_for_all_destinations():
    address = "9ABCDEFGHIJKLMNOPQRSTUVWXYZ1234567890"
    config = TelegramConfig(
        destinations=[
            TelegramDestination(chat_id="-10022222"),
            TelegramDestination(chat_id="-10033333", topic_id=7),
        ]
    )
    handler = MultiTelegramHandler(
        bot_token="token",
        address_configs={address: config},
        default_chat_id="-10044444",
    )

    monitor = SimpleNamespace(
        watched_addresses={
            address: SimpleNamespace(address=address, nickname="Hot Wallet")
        }
    )

    sent_messages = []

    async def fake_send_message(text, destination):
        sent_messages.append((text, destination))
        return True

    handler.send_message = fake_send_message  # type: ignore[assignment]

    await handler.handle_transaction(address, create_sample_transaction(), monitor)

    assert len(sent_messages) == 2
    message_text = sent_messages[0][0]
    assert "Hot Wallet" in message_text
    assert "Test Token" in message_text
    assert "tx123" in message_text
    destinations = [dest.chat_id for _, dest in sent_messages]
    assert "-10022222" in destinations
    assert "-10033333" in destinations


@pytest.mark.asyncio
async def test_send_message_uses_topic_id_and_returns_success():
    handler = MultiTelegramHandler(
        bot_token="token",
        address_configs={},
        default_chat_id=None,
    )

    destination = TelegramDestination(chat_id="-10055555", topic_id=42)

    def response_factory(url, payload):
        return DummyResponse(200, {"ok": True})

    handler.session = DummySession(response_factory)

    result = await handler.send_message("hello", destination)

    assert result is True
    assert handler.session.requests  # type: ignore[attr-defined]
    url, payload = handler.session.requests[0]  # type: ignore[attr-defined]
    assert url.endswith("/sendMessage")
    assert payload["chat_id"] == "-10055555"
    assert payload["message_thread_id"] == 42


