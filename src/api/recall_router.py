import logging
from aiohttp import web
from src.transcript.transcript_pipeline import extract_utterance_from_transcript_data

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
        bot_id = data.get("bot", {}).get("id") or data.get("bot_id", "unknown")

        utterance = extract_utterance_from_transcript_data(body, meeting_id=bot_id)
        if utterance is None:
            return web.Response(status=200)

        if self._cosmos is not None:
            try:
                await self._cosmos.save_utterance(utterance)
            except Exception:
                logger.exception("cosmos.save_utterance() failed for utterance %s", utterance.utterance_id)

        try:
            await self._orchestrator.process(utterance)
        except Exception:
            logger.exception("orchestrator.process() failed for utterance %s", utterance.utterance_id)

        return web.Response(status=202)
