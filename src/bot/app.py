# src/bot/app.py
from typing import Optional

from aiohttp import web
from botbuilder.core import BotFrameworkAdapter, BotFrameworkAdapterSettings
from botbuilder.schema import Activity

from src.bot.teams_bot import MeetingBot
from src.transcript.recall_source import RecallWebhookHandler
from src.transcript.recall_ws_handler import RecallWsHandler


def create_app_with_adapter(
    bot: MeetingBot,
    app_id: str,
    app_password: str,
    recall_handler: Optional[RecallWebhookHandler] = None,
    recall_ws_handler: Optional[RecallWsHandler] = None,
) -> tuple[web.Application, BotFrameworkAdapter]:
    settings = BotFrameworkAdapterSettings(app_id=app_id, app_password=app_password)
    adapter = BotFrameworkAdapter(settings)

    async def messages(req: web.Request) -> web.Response:
        body = await req.json()
        activity = Activity().deserialize(body)
        auth_header = req.headers.get("Authorization", "")
        response = await adapter.process_activity(activity, auth_header, bot.on_turn)
        if response:
            return web.json_response(data=response.body, status=response.status)
        return web.Response(status=201)

    async def notifications(req: web.Request) -> web.Response:
        """Graph API 変更通知の受信エンドポイント。"""
        validation_token = req.rel_url.query.get("validationToken")
        if validation_token:
            return web.Response(text=validation_token, content_type="text/plain")

        body = await req.json()
        for notification in body.get("value", []):
            await bot.handle_transcript_notification(notification)
        return web.Response(status=202)

    app = web.Application()
    app.router.add_post("/api/messages", messages)
    app.router.add_post("/api/notifications", notifications)
    if recall_handler is not None:
        app.router.add_post("/api/recall/webhook", recall_handler.handle)
    if recall_ws_handler is not None:
        app.router.add_get("/api/recall/ws", recall_ws_handler.handle)
    return app, adapter
