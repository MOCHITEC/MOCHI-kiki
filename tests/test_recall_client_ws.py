# tests/test_recall_client_ws.py
"""RecallBotClient の WebSocket 対応 (_build_create_body の出力) を検証する。"""
import pytest

from src.transcript.recall_client import RecallBotClient


_API_KEY = "test-key"
_HTTPS = "https://hook.example.com/api/recall/webhook"
_WSS = "wss://ws.example.com/api/recall/ws"
_MEETING = "https://teams.microsoft.com/l/meetup-join/xxx"


def _client(**kwargs) -> RecallBotClient:
    defaults = dict(
        api_key=_API_KEY,
        webhook_url=_HTTPS,
        region="us-east-1",
        bot_name="MOCHI-kiki",
        language_code="ja",
    )
    defaults.update(kwargs)
    return RecallBotClient(**defaults)


def test_webhook_only_transport_emits_single_webhook_endpoint() -> None:
    c = _client(transport="webhook")
    body = c._build_create_body(_MEETING)
    endpoints = body["recording_config"]["realtime_endpoints"]
    assert len(endpoints) == 1
    assert endpoints[0]["type"] == "webhook"
    assert endpoints[0]["url"] == _HTTPS
    assert endpoints[0]["events"] == ["transcript.data"]
    # audio_mixed_raw キーは WS 経路で audio_mixed_raw.data を購読するときだけ
    assert "audio_mixed_raw" not in body["recording_config"]


def test_websocket_only_transport_emits_single_ws_endpoint_with_audio_mixed_raw() -> None:
    c = _client(
        webhook_url=None,
        transport="websocket",
        ws_url=_WSS,
        ws_events=("audio_mixed_raw.data", "transcript.data"),
    )
    body = c._build_create_body(_MEETING)
    endpoints = body["recording_config"]["realtime_endpoints"]
    assert len(endpoints) == 1
    assert endpoints[0] == {
        "type": "websocket",
        "url": _WSS,
        "events": ["audio_mixed_raw.data", "transcript.data"],
    }
    # 公式: audio_mixed_raw.data を購読する場合は recording_config.audio_mixed_raw = {} が必要
    assert body["recording_config"]["audio_mixed_raw"] == {}


def test_websocket_transport_without_audio_event_omits_audio_mixed_raw_config() -> None:
    c = _client(
        webhook_url=None,
        transport="websocket",
        ws_url=_WSS,
        ws_events=("transcript.data",),
    )
    body = c._build_create_body(_MEETING)
    assert "audio_mixed_raw" not in body["recording_config"]
    endpoints = body["recording_config"]["realtime_endpoints"]
    assert endpoints[0]["events"] == ["transcript.data"]


def test_both_transport_emits_two_endpoints() -> None:
    c = _client(
        transport="both",
        ws_url=_WSS,
        ws_events=("audio_mixed_raw.data", "transcript.data"),
    )
    body = c._build_create_body(_MEETING)
    endpoints = body["recording_config"]["realtime_endpoints"]
    types = [ep["type"] for ep in endpoints]
    assert types == ["webhook", "websocket"]
    assert body["recording_config"]["audio_mixed_raw"] == {}


def test_websocket_requires_wss_scheme() -> None:
    with pytest.raises(ValueError):
        _client(
            webhook_url=None,
            transport="websocket",
            ws_url="ws://insecure.example/api/recall/ws",
            ws_events=("transcript.data",),
        )


def test_websocket_requires_non_empty_events() -> None:
    with pytest.raises(ValueError):
        _client(
            webhook_url=None,
            transport="websocket",
            ws_url=_WSS,
            ws_events=(),
        )


def test_unknown_transport_rejected() -> None:
    with pytest.raises(ValueError):
        _client(transport="grpc")


def test_webhook_transport_still_requires_https() -> None:
    with pytest.raises(ValueError):
        _client(webhook_url="http://insecure.example/", transport="webhook")


def test_realtime_mode_auto_selects_accuracy_for_japanese() -> None:
    c = _client(language_code="ja")
    body = c._build_create_body(_MEETING)
    assert (
        body["recording_config"]["transcript"]["provider"]["recallai_streaming"]["mode"]
        == "prioritize_accuracy"
    )


def test_realtime_mode_auto_selects_low_latency_for_english() -> None:
    c = _client(language_code="en")
    body = c._build_create_body(_MEETING)
    assert (
        body["recording_config"]["transcript"]["provider"]["recallai_streaming"]["mode"]
        == "prioritize_low_latency"
    )


def test_realtime_mode_auto_selects_low_latency_for_english_regional() -> None:
    c = _client(language_code="en-US")
    body = c._build_create_body(_MEETING)
    assert (
        body["recording_config"]["transcript"]["provider"]["recallai_streaming"]["mode"]
        == "prioritize_low_latency"
    )


def test_realtime_mode_explicit_override_is_respected() -> None:
    c = _client(language_code="ja", realtime_mode="prioritize_low_latency")
    body = c._build_create_body(_MEETING)
    assert (
        body["recording_config"]["transcript"]["provider"]["recallai_streaming"]["mode"]
        == "prioritize_low_latency"
    )


def test_realtime_mode_invalid_value_rejected() -> None:
    with pytest.raises(ValueError):
        _client(realtime_mode="turbo")
