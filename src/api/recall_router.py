import logging
from aiohttp import web
from src.models import Utterance

logger = logging.getLogger(__name__)


class RecallWebhookRouter:
    def __init__(self, orchestrator, cosmos=None) -> None:
        self._orchestrator = orchestrator
        self._cosmos = cosmos

    def register(self, app: web.Application) -> None:
        app.router.add_post("/api/recall/transcript", self._handle)

    async def _handle(self, req: web.Request) -> web.Response:
        body = await req.json()

        if body.get("event") != "transcript.data":
            return web.Response(status=200)

        data = body.get("data", {})
        inner = data.get("data", {})
        words = inner.get("words", [])

        if not words:
            return web.Response(status=200)

        text = " ".join(w.get("text", "") for w in words).strip()
        if not text:
            return web.Response(status=200)

        bot_id = data.get("bot_id", "unknown")
        speaker_name = inner.get("speaker", "不明")
        speaker_id = speaker_name.replace(" ", "-")

        utterance = Utterance.new(
            meeting_id=bot_id,
            speaker_id=speaker_id,
            speaker_name=speaker_name,
            text=text,
        )

        if self._cosmos is not None:
            await self._cosmos.save_utterance(utterance)

        try:
            await self._orchestrator.process(utterance)
        except Exception:
            logger.exception("orchestrator.process() failed for utterance %s", utterance.utterance_id)

        return web.Response(status=202)
