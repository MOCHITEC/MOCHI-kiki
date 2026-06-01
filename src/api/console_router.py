"""
MOCHI-kiki 管理コンソール (frontend-bot-console) 用 aiohttp ルータ。

仕様: docs/superpowers/specs/2026-05-29-frontend-bot-console.md
すべて `/api/console/*` プレフィックス。レスポンスは JSON / UTF-8 固定。
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import random
import secrets
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Awaitable, Callable, Optional

import bcrypt
import jwt
from aiohttp import web

from src.models import Utterance
from src.storage.cosmos_client import CosmosClient
from src.transcript.recall_client import RecallBotClient

logger = logging.getLogger(__name__)

SESSION_COOKIE = "mochi_session"
JWT_ALGO = "HS256"
JWT_TTL_SECONDS = 12 * 60 * 60  # 12h
LOGIN_RATE_LIMIT_WINDOW = 60.0
LOGIN_RATE_LIMIT_MAX = 10


def _now_utc() -> datetime:
    return datetime.now(tz=timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def _err(code: str, message: str, status: int) -> web.Response:
    return web.json_response(
        {"error": {"code": code, "message": message}}, status=status
    )


def _generate_meeting_id() -> str:
    ts = int(time.time())
    rand = "".join(
        random.choice("0123456789abcdef") for _ in range(4)
    )
    return f"console-{ts}-{rand}"


class _LoginRateLimiter:
    """IP 単位の in-memory バケット (MVP)。レプリカ間共有はしない。"""

    def __init__(self, *, window: float, max_attempts: int) -> None:
        self._window = window
        self._max = max_attempts
        self._buckets: dict[str, list[float]] = {}

    def hit(self, ip: str) -> bool:
        """True なら通過、False ならレート制限。"""
        if not ip:
            return True
        now = time.time()
        bucket = self._buckets.setdefault(ip, [])
        # 古い記録を削除
        cutoff = now - self._window
        while bucket and bucket[0] < cutoff:
            bucket.pop(0)
        if len(bucket) >= self._max:
            return False
        bucket.append(now)
        return True


class ConsoleRouter:
    def __init__(
        self,
        *,
        cosmos: CosmosClient,
        recall_client: Optional[RecallBotClient],
        username: str,
        password_hash: str,
        jwt_secret: str,
        cookie_secure: bool = True,
    ) -> None:
        if not username or not password_hash or not jwt_secret:
            raise ValueError(
                "ConsoleRouter: username / password_hash / jwt_secret は必須"
            )
        self._cosmos = cosmos
        self._recall = recall_client
        self._username = username
        self._password_hash = password_hash.encode("utf-8")
        self._jwt_secret = jwt_secret
        self._cookie_secure = cookie_secure
        self._login_limiter = _LoginRateLimiter(
            window=LOGIN_RATE_LIMIT_WINDOW, max_attempts=LOGIN_RATE_LIMIT_MAX
        )
        # オプション: テスト用 simulate_meeting で orchestrator.process を呼ぶ
        self._orchestrator = None  # type: ignore[assignment]

    def set_orchestrator(self, orchestrator) -> None:
        """テスト endpoint simulate_meeting で utterance を流すために orchestrator を inject。"""
        self._orchestrator = orchestrator

    # --- 登録 ---
    def register(self, app: web.Application) -> None:
        app.router.add_post("/api/console/auth/login", self._login)
        app.router.add_post("/api/console/auth/logout", self._logout)
        app.router.add_get("/api/console/auth/me", self._me)
        app.router.add_post("/api/console/bots", self._create_bot)
        app.router.add_post(
            "/api/console/bots/{bot_id}/leave", self._leave_bot
        )
        app.router.add_get("/api/console/meetings", self._list_meetings)
        app.router.add_get(
            "/api/console/meetings/{meeting_id}", self._get_meeting
        )
        app.router.add_get(
            "/api/console/meetings/{meeting_id}/utterances",
            self._list_utterances,
        )
        app.router.add_get(
            "/api/console/meetings/{meeting_id}/transcript.txt",
            self._transcript_txt,
        )
        app.router.add_get(
            "/api/console/meetings/{meeting_id}/minutes",
            self._get_minutes,
        )
        app.router.add_get(
            "/api/console/meetings/{meeting_id}/timeline",
            self._get_timeline,
        )
        app.router.add_post(
            "/api/console/test/simulate_meeting",
            self._test_simulate_meeting,
        )

    # --- JWT helpers ---
    def _issue_jwt(self, username: str) -> str:
        now = _now_utc()
        payload = {
            "sub": username,
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(seconds=JWT_TTL_SECONDS)).timestamp()),
        }
        return jwt.encode(payload, self._jwt_secret, algorithm=JWT_ALGO)

    def _verify_jwt(self, token: str) -> Optional[str]:
        try:
            payload = jwt.decode(token, self._jwt_secret, algorithms=[JWT_ALGO])
        except jwt.PyJWTError:
            return None
        sub = payload.get("sub")
        return sub if isinstance(sub, str) and sub else None

    def _set_session_cookie(self, resp: web.Response, token: str) -> None:
        resp.set_cookie(
            SESSION_COOKIE,
            token,
            max_age=JWT_TTL_SECONDS,
            httponly=True,
            secure=self._cookie_secure,
            samesite="Strict",
            path="/",
        )

    def _clear_session_cookie(self, resp: web.Response) -> None:
        resp.del_cookie(SESSION_COOKIE, path="/")

    def _require_auth(self, request: web.Request) -> Optional[str]:
        token = request.cookies.get(SESSION_COOKIE)
        if not token:
            return None
        return self._verify_jwt(token)

    # --- auth ---
    async def _login(self, request: web.Request) -> web.Response:
        ip = (
            request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
            or (request.remote or "")
        )
        if not self._login_limiter.hit(ip):
            return _err(
                "rate_limited",
                "ログイン試行回数の上限に達しました。1 分後に再試行してください。",
                429,
            )

        try:
            body = await request.json()
        except (json.JSONDecodeError, ValueError):
            return _err("invalid_body", "JSON 形式の body が必要です", 400)

        username = (body.get("username") or "").strip()
        password = body.get("password") or ""
        if not username or not password:
            return _err("invalid_body", "username と password は必須です", 400)

        # username 一致 + bcrypt 検証。タイミング攻撃を避けるため両方常に評価。
        username_ok = secrets.compare_digest(username, self._username)
        try:
            password_ok = bcrypt.checkpw(
                password.encode("utf-8"), self._password_hash
            )
        except ValueError:
            password_ok = False
        if not (username_ok and password_ok):
            return _err(
                "unauthorized", "ユーザ名またはパスワードが違います", 401
            )

        token = self._issue_jwt(username)
        resp = web.json_response({"username": username})
        self._set_session_cookie(resp, token)
        return resp

    async def _logout(self, request: web.Request) -> web.Response:
        resp = web.Response(status=204)
        self._clear_session_cookie(resp)
        return resp

    async def _me(self, request: web.Request) -> web.Response:
        username = self._require_auth(request)
        if not username:
            return _err("unauthorized", "認証が必要です", 401)
        return web.json_response({"username": username})

    # --- bot ---
    async def _create_bot(self, request: web.Request) -> web.Response:
        username = self._require_auth(request)
        if not username:
            return _err("unauthorized", "認証が必要です", 401)

        try:
            body = await request.json()
        except (json.JSONDecodeError, ValueError):
            return _err("invalid_body", "JSON 形式の body が必要です", 400)

        meeting_url = (body.get("meeting_url") or "").strip()
        bot_name = (body.get("bot_name") or "").strip() or None
        language_code = (body.get("language_code") or "").strip() or None

        if not meeting_url or not meeting_url.startswith(
            ("https://teams.microsoft.com/", "https://teams.live.com/")
        ):
            return _err(
                "invalid_meeting_url",
                "Teams 会議 URL (https://teams.microsoft.com/ または https://teams.live.com/) を指定してください",
                400,
            )

        if self._recall is None:
            return _err(
                "recall_unavailable",
                "サーバが Recall 連携を有効化していません (TRANSCRIPT_SOURCE / RECALL_TRANSPORT を確認してください)",
                503,
            )

        # MVP: bot_name / language_code は受け取るが既存 RecallBotClient のデフォルトを使う
        # (仕様 §4.2 注: 既存 RecallBotClient.create_bot を呼ぶ)
        if bot_name or language_code:
            logger.info(
                "ConsoleRouter.create_bot: bot_name/language_code overrides "
                "(name=%r, lang=%r) は MVP では無視します",
                bot_name, language_code,
            )

        bot_id = await self._recall.create_bot(meeting_url)
        if not bot_id:
            return _err(
                "recall_api_error",
                "Recall API への bot 投入に失敗しました",
                502,
            )

        meeting_id = _generate_meeting_id()
        now = _now_utc()
        item = {
            "id": meeting_id,
            "thread_id": "console",
            "organizer_id": username,
            "started_at": _iso(now),
            "ended_at": None,
            "transcript_subscription_id": None,
            "recall_bot_id": bot_id,
            "transcript_source": "recall",
            "meeting_url": meeting_url,
            "bot_name": bot_name or "MOCHI-kiki",
        }
        try:
            # 直接 upsert (Meeting dataclass は console 追加フィールドを持たない)
            await self._cosmos._meetings.upsert_item(item)  # type: ignore[attr-defined]
        except Exception:
            logger.exception(
                "ConsoleRouter.create_bot: cosmos upsert に失敗 (bot は投入済)"
            )
            return _err(
                "cosmos_error",
                "Cosmos への保存に失敗しました (bot は会議に参加中の可能性があります)",
                500,
            )

        return web.json_response(
            {"meeting_id": meeting_id, "bot_id": bot_id}, status=201
        )

    async def _leave_bot(self, request: web.Request) -> web.Response:
        username = self._require_auth(request)
        if not username:
            return _err("unauthorized", "認証が必要です", 401)

        if self._recall is None:
            return _err(
                "recall_unavailable",
                "サーバが Recall 連携を有効化していません",
                503,
            )

        bot_id = request.match_info["bot_id"]
        if not bot_id:
            return _err("invalid_body", "bot_id が空です", 400)

        ok = await self._recall.leave_call(bot_id)
        if not ok:
            return _err(
                "recall_api_error",
                "Recall API での退出に失敗しました",
                502,
            )

        # cosmos の meetings.ended_at をセット
        meeting_id = await self._cosmos.find_meeting_id_by_recall_bot_id_any(
            bot_id
        )
        if meeting_id:
            await self._cosmos.update_meeting_ended_at(
                meeting_id, _iso(_now_utc())
            )
        return web.Response(status=202)

    # --- meetings ---
    @staticmethod
    def _to_meeting_view(item: dict, utterance_count: int) -> dict:
        return {
            "meeting_id": item.get("id") or "",
            "bot_name": item.get("bot_name"),
            "meeting_url": item.get("meeting_url"),
            "recall_bot_id": item.get("recall_bot_id"),
            "started_at": item.get("started_at"),
            "ended_at": item.get("ended_at"),
            "utterance_count": utterance_count,
        }

    async def _list_meetings(self, request: web.Request) -> web.Response:
        if not self._require_auth(request):
            return _err("unauthorized", "認証が必要です", 401)

        try:
            limit = int(request.query.get("limit", "50"))
        except ValueError:
            limit = 50
        before = request.query.get("before") or None
        items = await self._cosmos.list_meetings_for_console(
            limit=limit, before=before
        )

        meetings = []
        for it in items:
            mid = it.get("id")
            count = await self._cosmos.count_utterances_for_meeting(mid)
            meetings.append(self._to_meeting_view(it, count))

        next_cursor: Optional[str] = None
        if items and len(items) >= limit:
            last = items[-1].get("started_at")
            if isinstance(last, str):
                next_cursor = last

        return web.json_response(
            {"meetings": meetings, "next_cursor": next_cursor}
        )

    async def _get_meeting(self, request: web.Request) -> web.Response:
        if not self._require_auth(request):
            return _err("unauthorized", "認証が必要です", 401)
        meeting_id = request.match_info["meeting_id"]
        item = await self._cosmos.get_meeting_for_console(meeting_id)
        if not item:
            return _err("meeting_not_found", "meeting が見つかりません", 404)
        count = await self._cosmos.count_utterances_for_meeting(meeting_id)
        return web.json_response(self._to_meeting_view(item, count))

    async def _list_utterances(self, request: web.Request) -> web.Response:
        if not self._require_auth(request):
            return _err("unauthorized", "認証が必要です", 401)
        meeting_id = request.match_info["meeting_id"]
        if not await self._cosmos.get_meeting_for_console(meeting_id):
            return _err("meeting_not_found", "meeting が見つかりません", 404)

        since = request.query.get("since") or None
        try:
            limit = int(request.query.get("limit", "500"))
        except ValueError:
            limit = 500
        items = await self._cosmos.list_utterances_for_meeting(
            meeting_id, since=since, limit=limit
        )
        utterances = [
            {
                "utterance_id": it.get("id"),
                "speaker": it.get("speaker_name") or it.get("speaker_id") or "",
                "text": it.get("text") or "",
                "timestamp": it.get("timestamp") or "",
                "is_final": it.get("is_final"),
            }
            for it in items
        ]
        return web.json_response({"utterances": utterances})

    async def _get_minutes(self, request: web.Request) -> web.Response:
        if not self._require_auth(request):
            return _err("unauthorized", "認証が必要です", 401)
        meeting_id = request.match_info["meeting_id"]
        item = await self._cosmos.get_meeting_for_console(meeting_id)
        if not item:
            return _err("meeting_not_found", "meeting が見つかりません", 404)
        return web.json_response(
            {
                "meeting_id": meeting_id,
                "markdown": item.get("minutes_markdown") or "",
                "updated_at": item.get("minutes_updated_at"),
                "utterance_count": item.get("minutes_utterance_count", 0),
            }
        )

    async def _get_timeline(self, request: web.Request) -> web.Response:
        if not self._require_auth(request):
            return _err("unauthorized", "認証が必要です", 401)
        meeting_id = request.match_info["meeting_id"]
        item = await self._cosmos.get_meeting_for_console(meeting_id)
        if not item:
            return _err("meeting_not_found", "meeting が見つかりません", 404)
        blocks = item.get("timeline_blocks") or []
        return web.json_response({"meeting_id": meeting_id, "blocks": blocks})

    async def _test_simulate_meeting(self, request: web.Request) -> web.Response:
        """テスト用: ダミー utterance 配列を流して議事録生成を試す。

        body: {
          "meeting_id": "test-...",  // 既存 or 新規
          "bot_name": "MOCHI-kiki",
          "delay_seconds": 0.5,       // 各 utterance を流す間隔 (デフォルト 0.5 秒)
          "utterances": [
            {"speaker": "...", "text": "..."},
            ...
          ]
        }
        """
        if not self._require_auth(request):
            return _err("unauthorized", "認証が必要です", 401)

        try:
            body = await request.json()
        except (json.JSONDecodeError, ValueError):
            return _err("invalid_body", "JSON 形式の body が必要です", 400)

        meeting_id = (body.get("meeting_id") or "").strip()
        if not meeting_id:
            meeting_id = f"test-sim-{int(time.time())}"
        bot_name = (body.get("bot_name") or "MOCHI-kiki").strip()
        delay = float(body.get("delay_seconds") or 0.5)
        utts_raw = body.get("utterances") or []
        if not isinstance(utts_raw, list) or not utts_raw:
            return _err("invalid_body", "utterances 配列が必要です", 400)

        # 既存 meeting の有無を確認、無ければ作成
        existing = await self._cosmos.get_meeting_for_console(meeting_id)
        if existing is None:
            now = _now_utc()
            meeting_item = {
                "id": meeting_id,
                "thread_id": "test-sim",
                "organizer_id": "test",
                "started_at": _iso(now),
                "ended_at": None,
                "transcript_subscription_id": None,
                "recall_bot_id": f"sim-{uuid.uuid4()}",
                "transcript_source": "test-simulate",
                "meeting_url": "https://teams.live.com/test-simulate",
                "bot_name": bot_name,
            }
            await self._cosmos._meetings.upsert_item(meeting_item)  # type: ignore[attr-defined]

        # バックグラウンドで utterance を順次流す
        async def _stream() -> None:
            for i, u in enumerate(utts_raw):
                speaker = (u.get("speaker") or "テスト発言者").strip()
                text = (u.get("text") or "").strip()
                if not text:
                    continue
                ts = datetime.now(tz=timezone.utc)
                utterance = Utterance(
                    utterance_id=str(uuid.uuid4()),
                    meeting_id=meeting_id,
                    speaker_id=f"sim-{speaker}",
                    speaker_name=speaker,
                    text=text,
                    timestamp=ts,
                )
                try:
                    await self._cosmos.save_utterance(utterance)
                except Exception:
                    logger.exception("simulate: save_utterance failed")
                if self._orchestrator is not None:
                    try:
                        await self._orchestrator.process(utterance)
                    except Exception:
                        logger.exception("simulate: orchestrator.process failed")
                if i < len(utts_raw) - 1 and delay > 0:
                    await asyncio.sleep(delay)
            # 全 utterance 流し終わったら議事録を強制再生成
            if self._orchestrator is not None and hasattr(
                self._orchestrator, "refresh_minutes"
            ):
                try:
                    await self._orchestrator.refresh_minutes(
                        meeting_id, force=True
                    )
                except Exception:
                    logger.exception("simulate: refresh_minutes failed")
            logger.info(
                "simulate_meeting completed meeting_id=%s count=%d",
                meeting_id, len(utts_raw),
            )

        asyncio.create_task(_stream())
        return web.json_response(
            {
                "meeting_id": meeting_id,
                "scheduled": len(utts_raw),
                "delay_seconds": delay,
                "view_url": (
                    f"/meeting?id={meeting_id}"
                ),
            },
            status=202,
        )

    async def _transcript_txt(self, request: web.Request) -> web.Response:
        if not self._require_auth(request):
            return _err("unauthorized", "認証が必要です", 401)
        meeting_id = request.match_info["meeting_id"]
        if not await self._cosmos.get_meeting_for_console(meeting_id):
            return _err("meeting_not_found", "meeting が見つかりません", 404)

        items = await self._cosmos.list_utterances_for_meeting(
            meeting_id, limit=5000
        )
        lines: list[str] = []
        for it in items:
            ts = it.get("timestamp") or ""
            speaker = it.get("speaker_name") or it.get("speaker_id") or "(不明)"
            text = it.get("text") or ""
            lines.append(f"[{ts}] {speaker}:\n    {text}")
        body = ("\n".join(lines) + "\n") if lines else ""
        return web.Response(
            text=body,
            headers={
                "Content-Type": "text/plain; charset=utf-8",
                "Content-Disposition": (
                    f'attachment; filename="{meeting_id}.txt"'
                ),
            },
        )


def build_console_router_from_env(
    *,
    cosmos: CosmosClient,
    recall_client: Optional[RecallBotClient],
    username: str,
    password_hash: str,
    jwt_secret: str,
) -> ConsoleRouter:
    cookie_secure = (
        os.environ.get("CONSOLE_COOKIE_SECURE", "true").strip().lower() != "false"
    )
    return ConsoleRouter(
        cosmos=cosmos,
        recall_client=recall_client,
        username=username,
        password_hash=password_hash,
        jwt_secret=jwt_secret,
        cookie_secure=cookie_secure,
    )
