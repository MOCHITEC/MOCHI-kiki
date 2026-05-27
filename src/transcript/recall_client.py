# src/transcript/recall_client.py
import asyncio
import logging
import re
from typing import Iterable, Optional

import aiohttp

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT = 10.0
_MAX_RETRIES = 3
_BASE_BACKOFF_SECONDS = 0.5
_RETRYABLE_STATUSES = {429, 500, 502, 503, 504}
_MAX_MEETING_URL_LEN = 2048
_REGION_PATTERN = re.compile(r"^[a-z0-9-]+$")
# Teams 系の join URL を許可。Microsoft/Live ドメインの bot framework 経由
_TEAMS_URL_PATTERN = re.compile(
    r"^https://teams\.(microsoft|live)\.com/[^\s]{1,2000}$"
)

_VALID_TRANSPORTS = {"webhook", "websocket", "both"}
# recallai_streaming provider の動作モード。
# prioritize_low_latency: 部分/確定イベントを realtime WS で随時送信する。
# prioritize_accuracy:    精度重視で realtime 送信を抑制し、batch transcript を中心に提供する。
# WS で transcript.data を確実に受け取りたい場合は前者を指定する。
_VALID_REALTIME_MODES = {"prioritize_low_latency", "prioritize_accuracy"}


class RecallBotClient:
    """
    Recall.ai のメタ API を叩く HTTP クライアント。
    実発話の受信は src/transcript/recall_source.py (webhook) または
    src/transcript/recall_ws_handler.py (websocket) 側で行う。

    例外は投げない（会議自体を Recall の失敗で壊さないため）。
    create_bot は失敗時 None、leave_call は失敗時 False を返す。
    """

    def __init__(
        self,
        api_key: str,
        webhook_url: Optional[str] = None,
        region: str = "ap-northeast-1",
        bot_name: str = "MOCHI-kiki",
        language_code: str = "ja",
        timeout_seconds: float = _DEFAULT_TIMEOUT,
        session: Optional[aiohttp.ClientSession] = None,
        *,
        transport: str = "webhook",
        ws_url: Optional[str] = None,
        ws_events: Optional[Iterable[str]] = None,
        realtime_mode: str = "prioritize_low_latency",
    ) -> None:
        if not api_key:
            raise ValueError("Recall api_key は必須")
        if transport not in _VALID_TRANSPORTS:
            raise ValueError(
                f"transport は {_VALID_TRANSPORTS} のいずれか (got {transport!r})"
            )
        if realtime_mode not in _VALID_REALTIME_MODES:
            raise ValueError(
                f"realtime_mode は {_VALID_REALTIME_MODES} のいずれか "
                f"(got {realtime_mode!r})"
            )
        if transport in ("webhook", "both"):
            if not webhook_url or not webhook_url.startswith("https://"):
                raise ValueError("Recall webhook_url は HTTPS でなければならない")
        if transport in ("websocket", "both"):
            if not ws_url or not ws_url.startswith("wss://"):
                raise ValueError("Recall ws_url は wss:// でなければならない")
        if not _REGION_PATTERN.fullmatch(region):
            raise ValueError(f"Recall region 形式不正: {region!r}")

        self._api_key = api_key
        self._webhook_url = webhook_url
        self._region = region
        self._bot_name = bot_name
        self._language_code = language_code
        self._timeout = aiohttp.ClientTimeout(total=timeout_seconds)
        self._owns_session = session is None
        self._session = session
        self._transport = transport
        self._ws_url = ws_url
        self._ws_events: tuple[str, ...] = tuple(ws_events or ())
        if transport in ("websocket", "both") and not self._ws_events:
            raise ValueError("transport が websocket/both の場合 ws_events は必須")
        self._realtime_mode = realtime_mode

    @property
    def _base_url(self) -> str:
        return f"https://{self._region}.recall.ai/api/v1"

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Token {self._api_key}",
            "Content-Type": "application/json",
        }

    async def _ensure_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(timeout=self._timeout)
            self._owns_session = True
        return self._session

    async def close(self) -> None:
        if self._owns_session and self._session is not None and not self._session.closed:
            await self._session.close()

    async def create_bot(self, meeting_url: str) -> Optional[str]:
        """
        Recall bot を会議に投入する。

        Returns: bot.id (UUID 文字列)。失敗時は None。
        """
        if not meeting_url:
            logger.warning("RecallBotClient.create_bot: meeting_url が空")
            return None
        if not self._is_valid_meeting_url(meeting_url):
            logger.warning("RecallBotClient.create_bot: meeting_url が許可形式外")
            return None

        body = self._build_create_body(meeting_url)
        url = f"{self._base_url}/bot/"

        response_body = await self._request_with_retry("POST", url, json=body)
        if response_body is None:
            return None

        bot_id = response_body.get("id")
        if not isinstance(bot_id, str) or not bot_id:
            logger.warning("RecallBotClient.create_bot: 応答に id が無い")
            return None
        return bot_id

    async def leave_call(self, bot_id: str) -> bool:
        """会議から bot を退出させる。成功/失敗を bool で返す。"""
        if not bot_id:
            return False
        url = f"{self._base_url}/bot/{bot_id}/leave_call/"
        result = await self._request_with_retry(
            "POST", url, expect_status={200, 202, 204}
        )
        # 成功時は dict (空でも可)、失敗時のみ None という契約
        return result is not None

    @staticmethod
    def _is_valid_meeting_url(url: str) -> bool:
        if len(url) > _MAX_MEETING_URL_LEN:
            return False
        # 制御文字 / ログインジェクション対策
        if any(c in url for c in ("\r", "\n", "\x00")):
            return False
        return bool(_TEAMS_URL_PATTERN.fullmatch(url))

    def _build_create_body(self, meeting_url: str) -> dict:
        realtime_endpoints: list[dict] = []
        if self._transport in ("webhook", "both"):
            realtime_endpoints.append(
                {
                    "type": "webhook",
                    "url": self._webhook_url,
                    "events": ["transcript.data"],
                }
            )
        if self._transport in ("websocket", "both"):
            realtime_endpoints.append(
                {
                    "type": "websocket",
                    "url": self._ws_url,
                    "events": list(self._ws_events),
                }
            )

        recording_config: dict = {
            "transcript": {
                "provider": {
                    "recallai_streaming": {
                        "language_code": self._language_code,
                        "mode": self._realtime_mode,
                    }
                },
                "diarization": {"use_separate_streams_when_available": True},
            },
            "realtime_endpoints": realtime_endpoints,
        }
        # 公式: audio_mixed_raw.data を WS で受け取る場合は
        # recording_config.audio_mixed_raw を有効化する必要がある
        if "audio_mixed_raw.data" in self._ws_events:
            recording_config["audio_mixed_raw"] = {}
        if "audio_separate_raw.data" in self._ws_events:
            recording_config["audio_separate_raw"] = {}

        return {
            "meeting_url": meeting_url,
            "bot_name": self._bot_name,
            "recording_config": recording_config,
        }

    async def _request_with_retry(
        self,
        method: str,
        url: str,
        *,
        json: Optional[dict] = None,
        expect_status: Optional[set[int]] = None,
    ) -> Optional[dict]:
        """
        失敗時 None を返す。429/5xx は exponential backoff でリトライ。
        成功時は JSON body（または空 dict）を返す。
        """
        expect_status = expect_status or {200, 201, 202}
        session = await self._ensure_session()

        for attempt in range(_MAX_RETRIES):
            try:
                async with session.request(
                    method, url, headers=self._headers, json=json
                ) as resp:
                    if resp.status in expect_status:
                        if resp.status == 204:
                            return {}
                        try:
                            data = await resp.json()
                            return data if isinstance(data, dict) else {}
                        except (aiohttp.ContentTypeError, ValueError):
                            return {}

                    if resp.status in _RETRYABLE_STATUSES and attempt < _MAX_RETRIES - 1:
                        backoff = _BASE_BACKOFF_SECONDS * (2 ** attempt)
                        logger.warning(
                            "RecallBotClient: %s %s -> %d, retry %d in %.1fs",
                            method, url, resp.status, attempt + 1, backoff,
                        )
                        await asyncio.sleep(backoff)
                        continue

                    # リトライ対象外 or リトライ枯渇。
                    # 応答 body はログに出さない（PII / 認可情報の漏洩防止）
                    request_id = resp.headers.get("x-request-id", "")
                    logger.warning(
                        "RecallBotClient: %s %s failed status=%d request_id=%s",
                        method, url, resp.status, request_id,
                    )
                    return None
            except asyncio.TimeoutError:
                logger.warning(
                    "RecallBotClient: %s %s timeout (attempt %d/%d)",
                    method, url, attempt + 1, _MAX_RETRIES,
                )
            except aiohttp.ClientError as exc:
                # exc 全体を出すと URL / 認可情報が混入する可能性。型名のみ。
                logger.warning(
                    "RecallBotClient: %s %s client error type=%s (attempt %d/%d)",
                    method, url, type(exc).__name__, attempt + 1, _MAX_RETRIES,
                )

            if attempt < _MAX_RETRIES - 1:
                await asyncio.sleep(_BASE_BACKOFF_SECONDS * (2 ** attempt))

        return None
