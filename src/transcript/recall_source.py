# src/transcript/recall_source.py
import base64
import binascii
import collections
import hashlib
import hmac
import logging
import time
from json import JSONDecodeError, loads as json_loads
from typing import TYPE_CHECKING, Awaitable, Callable, Mapping, Optional

from aiohttp import web

from src.models import Utterance
from src.transcript.transcript_pipeline import extract_utterance_from_transcript_data

if TYPE_CHECKING:
    from src.storage.cosmos_client import CosmosClient

logger = logging.getLogger(__name__)

# Svix の timestamp は Unix epoch（秒）。リプレイ防御の許容ウィンドウ。
_REPLAY_TOLERANCE_SECONDS = 5 * 60

# Svix の secret は "whsec_<base64>" 形式
_SVIX_SECRET_PREFIX = "whsec_"

# 入力の上限（DoS 防御）
_MAX_REQUEST_BODY_BYTES = 64 * 1024
_MAX_TIMESTAMP_DIGITS = 16
_MAX_TEXT_FIELD_LEN = 200
_MAX_WORDS = 500
_MAX_BOT_MAPPINGS = 10_000

# svix-id LRU（リプレイ防御。bounded）
_SEEN_IDS_CAPACITY = 10_000


class RecallSecretError(ValueError):
    """Webhook secret の形式が不正。起動時に致命扱いにする。"""


class RecallWebhookHandler:
    """
    Recall.ai (Svix 経由) の real-time webhook を受信し、
    Utterance に変換して既存パイプラインに流す push 型ハンドラ。

    UtteranceSource (pull 型抽象) は継承しない。
    既存 GraphTranscriptSubscription と並列の「もう一つの発話ソース」として位置づける。
    """

    def __init__(
        self,
        cosmos_client: "CosmosClient",
        on_utterance: Callable[[Utterance], Awaitable[None]],
        webhook_secret: Optional[str] = None,
        clock: Callable[[], float] = time.time,
        insecure_mode: bool = False,
    ) -> None:
        self._cosmos = cosmos_client
        self._on_utterance = on_utterance
        self._clock = clock
        self._insecure_mode = insecure_mode

        # secret は起動時にデコードし、形式不正なら fail-fast
        self._secret_bytes: Optional[bytes] = None
        if webhook_secret:
            self._secret_bytes = self._decode_secret(webhook_secret)
        elif not insecure_mode:
            logger.warning(
                "RecallWebhookHandler: secret 未設定。全リクエストを 401 で拒否します。"
            )

        # bot.id (Recall) -> meeting_id (Teams)。プロセス内メモリ。
        # NOTE: 単一レプリカ前提。複数レプリカで運用する場合は Cosmos に永続化する必要あり。
        self._bot_to_meeting: dict[str, str] = {}
        # svix-id のリプレイ防御用 LRU
        self._seen_svix_ids: collections.OrderedDict[str, None] = collections.OrderedDict()

    def set_on_utterance(self, on_utterance: Callable[[Utterance], Awaitable[None]]) -> None:
        """主に main.py の起動シーケンスで orchestrator 完成後に差し替えるためのフック。"""
        self._on_utterance = on_utterance

    def register_bot(self, bot_id: str, meeting_id: str) -> None:
        """Recall bot 投入時に呼び、bot.id と Teams meeting_id を紐付ける。"""
        if len(self._bot_to_meeting) >= _MAX_BOT_MAPPINGS:
            logger.error("RecallWebhookHandler: bot マッピング上限 %d 到達。登録拒否。", _MAX_BOT_MAPPINGS)
            return
        self._bot_to_meeting[bot_id] = meeting_id

    def unregister_bot(self, bot_id: str) -> None:
        self._bot_to_meeting.pop(bot_id, None)

    def is_bot_registered(self, bot_id: str) -> bool:
        return bot_id in self._bot_to_meeting

    async def handle(self, request: web.Request) -> web.Response:
        """aiohttp ルートから呼ばれるエントリポイント。"""
        if request.content_length is not None and request.content_length > _MAX_REQUEST_BODY_BYTES:
            return web.Response(status=413)

        try:
            raw_body = await request.read()
        except Exception:
            logger.exception("RecallWebhookHandler: body 読み取り失敗")
            return web.Response(status=400)

        if len(raw_body) > _MAX_REQUEST_BODY_BYTES:
            return web.Response(status=413)

        svix_id = request.headers.get("svix-id", "")
        if not self._verify_request(request.headers, raw_body):
            return web.Response(status=401)

        # リプレイ防御: 同一 svix-id を再受信したら破棄
        if svix_id and self._is_replay(svix_id):
            logger.info("RecallWebhookHandler: 重複 svix-id を無視 (id=%s)", svix_id)
            return web.Response(status=200)

        try:
            payload = json_loads(raw_body)
        except JSONDecodeError:
            return web.Response(status=400)
        if not isinstance(payload, dict):
            return web.Response(status=400)

        event = payload.get("event", "")
        try:
            await self._dispatch(event, payload)
        except (KeyError, TypeError, ValueError):
            # 入力起因のバグ。サニタイズした最小情報のみログに残し、200 で抑止。
            logger.exception(
                "RecallWebhookHandler: dispatch failed (event=%s, svix_id=%s)",
                event, svix_id,
            )
        except Exception:
            # 想定外。リトライ嵐回避のため 200 を返すが、必ず可視化する。
            logger.exception(
                "RecallWebhookHandler: unexpected error (event=%s, svix_id=%s)",
                event, svix_id,
            )

        return web.Response(status=200)

    async def _dispatch(self, event: str, payload: dict) -> None:
        if event == "transcript.data":
            await self._handle_transcript(payload)
        elif event == "bot.status_change":
            self._handle_bot_status(payload)
        else:
            # 未知 event は INFO で残す（設定漏れ検知のため）
            logger.info("RecallWebhookHandler: unhandled event=%s", event)

    async def _handle_transcript(self, payload: dict) -> None:
        data_outer = payload.get("data") or {}
        bot = data_outer.get("bot") if isinstance(data_outer, dict) else None
        bot_id = bot.get("id") if isinstance(bot, dict) else None
        if not isinstance(bot_id, str) or not bot_id:
            return

        meeting_id = self._bot_to_meeting.get(bot_id)
        if not meeting_id:
            # 未登録 bot からの webhook は警告のみ（PII は出さない）
            logger.warning("RecallWebhookHandler: 未登録 bot からの webhook を無視")
            return

        utterance = extract_utterance_from_transcript_data(payload, meeting_id=meeting_id)
        if utterance is None:
            return

        await self._cosmos.save_utterance(utterance)
        await self._on_utterance(utterance)

    def _handle_bot_status(self, payload: dict) -> None:
        data = payload.get("data") or {}
        if not isinstance(data, dict):
            return
        bot = data.get("bot") if isinstance(data.get("bot"), dict) else {}
        bot_id = bot.get("id") if isinstance(bot, dict) else None
        raw_status = data.get("status")
        # Recall は status をオブジェクト ({code: "..."}) または文字列で送る可能性がある
        if isinstance(raw_status, dict):
            status = raw_status.get("code")
        else:
            status = raw_status

        # 終端ステータスはマッピングから削除
        terminal_statuses = {"done", "fatal", "call_ended", "media_expired"}
        if isinstance(status, str) and status in terminal_statuses and isinstance(bot_id, str):
            self.unregister_bot(bot_id)
        logger.info("RecallWebhookHandler: bot status changed (status=%s)", status)

    def _verify_request(self, headers: Mapping[str, str], raw_body: bytes) -> bool:
        if self._insecure_mode:
            logger.warning("RecallWebhookHandler: insecure_mode で署名検証をバイパス")
            return True
        if self._secret_bytes is None:
            return False

        msg_id = headers.get("svix-id", "")
        msg_ts = headers.get("svix-timestamp", "")
        msg_sig = headers.get("svix-signature", "")
        if not (msg_id and msg_ts and msg_sig):
            return False

        # 巨大整数による CPU 消費を避けるため、桁数・形式をまず確認
        if len(msg_ts) > _MAX_TIMESTAMP_DIGITS or not msg_ts.isdigit():
            return False
        ts = int(msg_ts)
        # 未来側のクロックスキューも同じ窓でガード
        if abs(self._clock() - ts) > _REPLAY_TOLERANCE_SECONDS:
            return False

        signed_payload = f"{msg_id}.{msg_ts}.".encode("utf-8") + raw_body
        expected = base64.b64encode(
            hmac.new(self._secret_bytes, signed_payload, hashlib.sha256).digest()
        ).decode("ascii")

        # Svix は複数署名をスペース区切りで送る: "v1,xxx v1,yyy"
        for token in msg_sig.strip().split():
            scheme, _, sig = token.partition(",")
            if scheme != "v1" or not sig:
                continue
            if hmac.compare_digest(sig.strip(), expected):
                return True
        return False

    def _is_replay(self, svix_id: str) -> bool:
        """同一 svix-id を一度処理したら以降は再生扱い。bounded LRU。"""
        if svix_id in self._seen_svix_ids:
            # 最新アクセス位置に移動（ホット ID を窓内に保持）
            self._seen_svix_ids.move_to_end(svix_id)
            return True
        self._seen_svix_ids[svix_id] = None
        if len(self._seen_svix_ids) > _SEEN_IDS_CAPACITY:
            self._seen_svix_ids.popitem(last=False)
        return False

    @staticmethod
    def _decode_secret(secret: str) -> bytes:
        if secret.startswith(_SVIX_SECRET_PREFIX):
            secret = secret[len(_SVIX_SECRET_PREFIX):]
        try:
            return base64.b64decode(secret, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise RecallSecretError("Recall webhook secret の base64 デコードに失敗") from exc

    @staticmethod
    def _join_words(words: list) -> str:
        # 日本語が中心。ASCII 空白は挿入しない。
        # Recall の word.text に既に必要な区切りが含まれている前提。
        parts: list[str] = []
        for w in words:
            if not isinstance(w, dict):
                continue
            t = w.get("text")
            if isinstance(t, str):
                parts.append(t)
        return "".join(parts).strip()

    @staticmethod
    def _sanitize_text(value, default: str) -> str:
        if value is None:
            return default
        s = str(value)
        if not s:
            return default
        return s[:_MAX_TEXT_FIELD_LEN]
