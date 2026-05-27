# src/transcript/recall_ws_handler.py
"""
Recall.ai の WebSocket realtime endpoint を受ける aiohttp サーバ側ハンドラ。

- Recall がクライアント、我々がサーバ。bot 作成時に
  recording_config.realtime_endpoints[].url で本ハンドラを指す wss URL を渡す。
- Upgrade ハンドシェイク時に Svix 互換 HMAC-SHA256 で認証 (body 空)。
- 各メッセージ JSON envelope の event で audio_mixed_raw.data / transcript.data / その他に分岐。

設計の根拠は docs/superpowers/specs/2026-05-22-recall-websocket-audio.md を参照。
"""
from __future__ import annotations

import asyncio
import base64
import binascii
import collections
import hashlib
import hmac
import json
import logging
import time
from typing import TYPE_CHECKING, Awaitable, Callable, Mapping, Optional

from aiohttp import WSCloseCode, WSMsgType, web

from src.models import Utterance
from src.transcript.audio_sink import AudioSink, NoopAudioSink
from src.transcript.transcript_pipeline import extract_utterance_from_transcript_data

if TYPE_CHECKING:
    from src.storage.cosmos_client import CosmosClient
    from src.transcript.recall_source import RecallWebhookHandler

logger = logging.getLogger(__name__)

_REPLAY_TOLERANCE_SECONDS = 5 * 60
_SVIX_SECRET_PREFIX = "whsec_"
_MAX_TIMESTAMP_DIGITS = 16
_DEFAULT_HEARTBEAT_SECONDS = 30.0
_AUDIO_SAMPLE_RATE = 16_000

# bot_id 解決を待つ間に貯めるフレーム数の上限（最初の数フレームで bot.id が分かる前提）
_PENDING_FRAME_LIMIT = 64
# テキストフレーム長の安全上限。
# 16 kHz mono S16LE で約 30 秒分。Recall の典型送信は 100-200 ms 毎なので十分な余裕。
_MAX_FRAME_BYTES = 1 * 1024 * 1024


class RecallWsSecretError(ValueError):
    """WS secret の形式が不正。起動時に致命扱いにする。"""


class RecallWsHandler:
    """
    Recall.ai realtime WebSocket 接続を 1 本ずつハンドルする。

    使い方:
        handler = RecallWsHandler(...)
        async def ws_endpoint(req): return await handler.handle(req)
        app.router.add_get("/api/recall/ws", ws_endpoint)
    """

    def __init__(
        self,
        cosmos_client: "CosmosClient",
        on_utterance: Callable[[Utterance], Awaitable[None]],
        audio_sink: Optional[AudioSink] = None,
        webhook_secret: Optional[str] = None,
        webhook_handler: Optional["RecallWebhookHandler"] = None,
        clock: Callable[[], float] = time.time,
        heartbeat_seconds: float = _DEFAULT_HEARTBEAT_SECONDS,
    ) -> None:
        self._cosmos = cosmos_client
        self._on_utterance = on_utterance
        self._audio_sink: AudioSink = audio_sink or NoopAudioSink()
        self._webhook_handler = webhook_handler
        self._clock = clock
        self._max_frame_bytes = _MAX_FRAME_BYTES
        self._heartbeat = heartbeat_seconds

        self._secret_bytes: Optional[bytes] = None
        if webhook_secret:
            self._secret_bytes = self._decode_secret(webhook_secret)
        else:
            logger.warning(
                "RecallWsHandler: secret 未設定。Upgrade を全て 401 で拒否します。"
            )

        # 同一 svix-id のリプレイ防御
        self._seen_ids: collections.OrderedDict[str, None] = collections.OrderedDict()
        self._seen_ids_cap = 10_000

    def set_on_utterance(self, on_utterance: Callable[[Utterance], Awaitable[None]]) -> None:
        self._on_utterance = on_utterance

    def set_audio_sink(self, sink: AudioSink) -> None:
        self._audio_sink = sink

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    async def handle(self, request: web.Request) -> web.StreamResponse:
        """aiohttp の GET ハンドラ。Upgrade 認証してから WS ループへ。"""
        if not self._verify_upgrade(request.headers):
            return web.Response(status=401)

        ws = web.WebSocketResponse(
            heartbeat=self._heartbeat,
            max_msg_size=self._max_frame_bytes,
        )
        await ws.prepare(request)
        logger.info("RecallWsHandler: WS established remote=%s", request.remote)

        session = _ConnectionState()
        try:
            await self._loop(ws, session)
        except asyncio.CancelledError:
            logger.info("RecallWsHandler: connection cancelled")
            raise
        except Exception:
            logger.exception("RecallWsHandler: unexpected handler failure")
        finally:
            await self._close_session(session, reason="closed")
            if not ws.closed:
                await ws.close()
            logger.info(
                "RecallWsHandler: closed bot_id=%s msgs=%d audio_bytes=%d drops=%d "
                "transcript_final=%d transcript_partial=%d extract_none=%d",
                session.bot_id, session.msg_count, session.audio_bytes, session.drop_count,
                session.transcript_final_count, session.transcript_partial_count,
                session.transcript_extract_none_count,
            )
        return ws

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    async def _loop(self, ws: web.WebSocketResponse, session: "_ConnectionState") -> None:
        async for msg in ws:
            if msg.type == WSMsgType.TEXT:
                await self._on_text(ws, session, msg.data)
            elif msg.type == WSMsgType.BINARY:
                # v1.11 envelope は JSON text のみ。binary は来ない想定。
                logger.warning(
                    "RecallWsHandler: 予期しない binary frame を破棄 bytes=%d",
                    len(msg.data),
                )
            elif msg.type in (WSMsgType.CLOSE, WSMsgType.CLOSING, WSMsgType.CLOSED):
                break
            elif msg.type == WSMsgType.ERROR:
                logger.warning("RecallWsHandler: WS error %s", ws.exception())
                break

    async def _on_text(
        self, ws: web.WebSocketResponse, session: "_ConnectionState", raw: str
    ) -> None:
        session.msg_count += 1

        if len(raw) > self._max_frame_bytes:
            session.drop_count += 1
            logger.warning("RecallWsHandler: text frame too large bytes=%d, dropped", len(raw))
            return

        try:
            payload = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            session.drop_count += 1
            logger.warning("RecallWsHandler: JSON parse failed")
            return
        if not isinstance(payload, dict):
            session.drop_count += 1
            return

        event = payload.get("event", "")
        bot_id = self._extract_bot_id(payload)

        # 接続単位で 1 度だけ bot_id → meeting_id を解決
        if session.bot_id is None and bot_id:
            resolved = await self._resolve_meeting_id(bot_id)
            if not resolved:
                # フォールバック: 正規の MeetingBot 経由でないテスト・実験用途で
                # mapping が無くてもデータを受け取れるよう bot_id を meeting_id として扱う。
                # 本番運用で MeetingBot 経由なら _resolve_meeting_id がヒットするのでここに来ない。
                resolved = bot_id
                logger.info(
                    "RecallWsHandler: meeting_id 未登録 → bot_id をフォールバック使用 bot_id=%s",
                    bot_id,
                )
            session.bot_id = bot_id
            session.meeting_id = resolved
            await self._safe_sink_open(
                meeting_id=resolved, bot_id=bot_id, sample_rate=_AUDIO_SAMPLE_RATE
            )
            # 解決前に貯めていたフレームを flush
            for pending_event, pending_payload in session.pending:
                await self._dispatch(session, pending_event, pending_payload)
            session.pending.clear()

        if session.bot_id is None:
            # まだ解決前 → ペンディング
            if len(session.pending) >= _PENDING_FRAME_LIMIT:
                session.drop_count += 1
                # 古いものから捨てる
                session.pending.popleft()
            session.pending.append((event, payload))
            return

        if bot_id and bot_id != session.bot_id:
            # 想定外（1 接続で複数 bot は発生しない）
            session.drop_count += 1
            logger.warning(
                "RecallWsHandler: 別 bot_id が同一接続で出現 cur=%s new=%s, dropped",
                session.bot_id, bot_id,
            )
            return

        await self._dispatch(session, event, payload)

    async def _dispatch(
        self, session: "_ConnectionState", event: str, payload: dict
    ) -> None:
        try:
            if event == "audio_mixed_raw.data":
                await self._handle_audio(session, payload)
            elif event == "audio_separate_raw.data":
                # 同梱仕様：data.data.buffer の先頭 4byte が participant_id LE uint32
                # 本 spec の最小実装では未対応。ログのみ
                logger.info(
                    "RecallWsHandler: audio_separate_raw.data 未対応 (drop)"
                )
            elif event in ("transcript.data", "transcript.partial_data"):
                await self._handle_transcript(session, payload, partial=event.endswith("partial_data"))
            elif event.startswith("participant_events."):
                logger.info("RecallWsHandler: participant event %s", event)
            else:
                logger.info("RecallWsHandler: unknown event=%s", event)
        except (KeyError, TypeError, ValueError):
            logger.exception("RecallWsHandler: dispatch failed event=%s", event)
        except Exception:
            logger.exception("RecallWsHandler: unexpected error event=%s", event)

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    async def _handle_audio(self, session: "_ConnectionState", payload: dict) -> None:
        if session.meeting_id is None:
            return
        data_outer = payload.get("data") or {}
        if not isinstance(data_outer, dict):
            return
        data = data_outer.get("data") or {}
        if not isinstance(data, dict):
            return
        buffer_b64 = data.get("buffer")
        if not isinstance(buffer_b64, str) or not buffer_b64:
            return
        try:
            pcm = base64.b64decode(buffer_b64, validate=True)
        except (binascii.Error, ValueError):
            session.drop_count += 1
            logger.warning("RecallWsHandler: base64 decode failed")
            return

        timestamp = data.get("timestamp") or {}
        if not isinstance(timestamp, dict):
            timestamp = {}
        absolute_ts = str(timestamp.get("absolute", ""))[:64]
        relative_ts_raw = timestamp.get("relative", 0.0)
        try:
            relative_ts = float(relative_ts_raw)
        except (TypeError, ValueError):
            relative_ts = 0.0

        session.audio_bytes += len(pcm)
        try:
            await self._audio_sink.push(
                meeting_id=session.meeting_id,
                pcm_bytes=pcm,
                absolute_ts=absolute_ts,
                relative_ts=relative_ts,
            )
        except Exception:
            logger.exception("RecallWsHandler: audio sink push failed")

    async def _handle_transcript(
        self, session: "_ConnectionState", payload: dict, *, partial: bool
    ) -> None:
        if session.meeting_id is None:
            return
        if partial:
            # partial は orchestrator に流さない（既存規約と整合）。
            # 必要な場合は spec FT-RECALL-WS-PARTIAL で扱う。
            session.transcript_partial_count += 1
            if session.transcript_partial_count <= 5 or session.transcript_partial_count % 50 == 0:
                logger.info(
                    "RecallWsHandler: transcript.partial received n=%d (dropped)",
                    session.transcript_partial_count,
                )
            return
        session.transcript_final_count += 1
        utterance = extract_utterance_from_transcript_data(
            payload, meeting_id=session.meeting_id
        )
        if utterance is None:
            session.transcript_extract_none_count += 1
            # 何が原因で None になっているか診断するための形状ダンプ。
            # 発話内容自体はログに残さない (text は長さのみ)。
            shape = _summarize_transcript_payload(payload)
            logger.info(
                "RecallWsHandler: transcript.data received but extract returned None "
                "n=%d shape=%s",
                session.transcript_extract_none_count, shape,
            )
            return
        # 発話内容自体はログに残さない（PII 配慮）。長さのみ記録。
        text_len = len(getattr(utterance, "text", "") or "")
        logger.info(
            "RecallWsHandler: transcript.data extracted utterance_id=%s text_len=%d",
            utterance.utterance_id, text_len,
        )
        try:
            await self._cosmos.save_utterance(utterance)
        except Exception:
            logger.exception(
                "RecallWsHandler: cosmos.save_utterance failed utterance=%s",
                utterance.utterance_id,
            )
        try:
            await self._on_utterance(utterance)
        except Exception:
            logger.exception(
                "RecallWsHandler: on_utterance failed utterance=%s",
                utterance.utterance_id,
            )

    # ------------------------------------------------------------------
    # Auth & helpers
    # ------------------------------------------------------------------

    def _verify_upgrade(self, headers: Mapping[str, str]) -> bool:
        if self._secret_bytes is None:
            return False

        msg_id = headers.get("webhook-id") or headers.get("svix-id", "")
        msg_ts = headers.get("webhook-timestamp") or headers.get("svix-timestamp", "")
        msg_sig = headers.get("webhook-signature") or headers.get("svix-signature", "")
        if not (msg_id and msg_ts and msg_sig):
            return False
        if len(msg_ts) > _MAX_TIMESTAMP_DIGITS or not msg_ts.isdigit():
            return False
        ts = int(msg_ts)
        if abs(self._clock() - ts) > _REPLAY_TOLERANCE_SECONDS:
            return False
        # リプレイ防御
        if msg_id in self._seen_ids:
            self._seen_ids.move_to_end(msg_id)
            return False
        self._seen_ids[msg_id] = None
        if len(self._seen_ids) > self._seen_ids_cap:
            self._seen_ids.popitem(last=False)

        # Upgrade 時の body は空
        signed = f"{msg_id}.{msg_ts}.".encode("utf-8")
        expected = base64.b64encode(
            hmac.new(self._secret_bytes, signed, hashlib.sha256).digest()
        ).decode("ascii")
        for token in msg_sig.strip().split():
            scheme, _, sig = token.partition(",")
            if scheme != "v1" or not sig:
                continue
            if hmac.compare_digest(sig.strip(), expected):
                return True
        return False

    async def _resolve_meeting_id(self, bot_id: str) -> Optional[str]:
        # 1) インメモリ（同レプリカで bot 投入 → 受信した場合）
        if self._webhook_handler and self._webhook_handler.is_bot_registered(bot_id):
            return self._webhook_handler._bot_to_meeting.get(bot_id)  # noqa: SLF001
        # 2) Cosmos fallback
        try:
            return await self._cosmos.find_meeting_id_by_recall_bot_id(bot_id)
        except Exception:
            logger.exception(
                "RecallWsHandler: Cosmos lookup failed for bot_id=%s", bot_id
            )
            return None

    async def _safe_sink_open(
        self, *, meeting_id: str, bot_id: str, sample_rate: int
    ) -> None:
        try:
            await self._audio_sink.on_open(
                meeting_id=meeting_id, bot_id=bot_id, sample_rate=sample_rate
            )
        except Exception:
            logger.exception("RecallWsHandler: audio sink on_open failed")

    async def _close_session(self, session: "_ConnectionState", *, reason: str) -> None:
        if session.meeting_id is None:
            return
        try:
            await self._audio_sink.on_close(meeting_id=session.meeting_id, reason=reason)
        except Exception:
            logger.exception("RecallWsHandler: audio sink on_close failed")

    @staticmethod
    def _extract_bot_id(payload: dict) -> Optional[str]:
        data = payload.get("data")
        if not isinstance(data, dict):
            return None
        bot = data.get("bot")
        if not isinstance(bot, dict):
            return None
        bot_id = bot.get("id")
        return bot_id if isinstance(bot_id, str) and bot_id else None

    @staticmethod
    def _decode_secret(secret: str) -> bytes:
        if secret.startswith(_SVIX_SECRET_PREFIX):
            secret = secret[len(_SVIX_SECRET_PREFIX):]
        try:
            return base64.b64decode(secret, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise RecallWsSecretError(
                "Recall WS secret の base64 デコードに失敗"
            ) from exc


def _summarize_transcript_payload(payload: dict) -> str:
    """transcript.data の構造だけ要約 (PII 漏洩防止のため value は出さない)。

    出力例:
        keys=[event,data] data_keys=[data,bot] inner_keys=[is_final,words,participant]
        is_final=False words_type=list words_n=3 word0_type=dict word0_keys=[text]
    """
    parts: list[str] = []
    try:
        parts.append(f"keys={list(payload.keys()) if isinstance(payload, dict) else type(payload).__name__}")
        data_outer = payload.get("data") if isinstance(payload, dict) else None
        parts.append(f"data_type={type(data_outer).__name__}")
        if isinstance(data_outer, dict):
            parts.append(f"data_keys={list(data_outer.keys())}")
            inner = data_outer.get("data")
            parts.append(f"inner_type={type(inner).__name__}")
            if isinstance(inner, dict):
                parts.append(f"inner_keys={list(inner.keys())}")
                parts.append(f"is_final={inner.get('is_final')!r}")
                w = inner.get("words")
                parts.append(f"words_type={type(w).__name__}")
                if isinstance(w, list):
                    parts.append(f"words_n={len(w)}")
                    if w:
                        w0 = w[0]
                        parts.append(f"word0_type={type(w0).__name__}")
                        if isinstance(w0, dict):
                            parts.append(f"word0_keys={list(w0.keys())}")
                        elif isinstance(w0, str):
                            parts.append(f"word0_len={len(w0)}")
    except Exception as e:
        parts.append(f"summarize_error={type(e).__name__}")
    return " ".join(parts)


class _ConnectionState:
    """1 WebSocket 接続のローカル状態。"""
    __slots__ = (
        "bot_id", "meeting_id", "pending", "msg_count", "audio_bytes", "drop_count",
        "transcript_final_count", "transcript_partial_count",
        "transcript_extract_none_count",
    )

    def __init__(self) -> None:
        self.bot_id: Optional[str] = None
        self.meeting_id: Optional[str] = None
        self.pending: collections.deque[tuple[str, dict]] = collections.deque()
        self.msg_count: int = 0
        self.audio_bytes: int = 0
        self.drop_count: int = 0
        self.transcript_final_count: int = 0
        self.transcript_partial_count: int = 0
        self.transcript_extract_none_count: int = 0
