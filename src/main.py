import asyncio
import logging
from typing import Optional

from aiohttp import web
from src.config import Config
from src.storage.cosmos_client import CosmosClient
from src.transcript.graph_subscription import GraphTranscriptSubscription
from src.transcript.recall_source import RecallWebhookHandler
from src.transcript.recall_client import RecallBotClient
from src.transcript.recall_ws_handler import RecallWsHandler
from src.transcript.audio_sink import build_audio_sink
from src.bot.teams_bot import MeetingBot
from src.bot.app import create_app_with_adapter
from src.kernel.orchestrator import Orchestrator
from src.models import Utterance
from src.api.recall_router import RecallWebhookRouter

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def main() -> None:
    config = Config()

    # 1. cosmos + graph_sub
    cosmos = CosmosClient(
        endpoint=config.cosmos_endpoint,
        key=config.cosmos_key,
        database_name=config.cosmos_database,
    )
    await cosmos.initialize()
    logger.info("Cosmos DB 接続完了")

    graph_sub = GraphTranscriptSubscription(
        tenant_id=config.graph_tenant_id,
        client_id=config.graph_client_id,
        client_secret=config.graph_client_secret,
        notification_url=config.graph_notification_url,
    )

    # 2. Recall webhook handler (on_utterance は orchestrator 完成後に set_on_utterance で注入)
    async def _placeholder_on_utterance(utterance: Utterance) -> None:
        return None

    recall_handler = RecallWebhookHandler(
        cosmos_client=cosmos,
        on_utterance=_placeholder_on_utterance,
        webhook_secret=config.recall_webhook_secret,
        insecure_mode=config.recall_webhook_insecure,
    )

    # 2.b Recall WS handler (transport が websocket/both のとき有効)
    recall_ws_handler: Optional[RecallWsHandler] = None
    if config.recall_transport in ("websocket", "both"):
        audio_sink = build_audio_sink(config.recall_audio_sink)
        recall_ws_handler = RecallWsHandler(
            cosmos_client=cosmos,
            on_utterance=_placeholder_on_utterance,
            audio_sink=audio_sink,
            webhook_secret=config.recall_webhook_secret,
            webhook_handler=recall_handler,
            insecure_mode=config.recall_webhook_insecure,
            max_frame_bytes=config.recall_ws_max_frame_bytes,
        )
        logger.info(
            "RecallWsHandler 起動 (audio_sink=%s, events=%s)",
            config.recall_audio_sink, config.recall_ws_events,
        )

    # 3. Recall bot client (transcript_source が recall/both のときのみ)
    recall_client: Optional[RecallBotClient] = None
    if config.transcript_source in ("recall", "both"):
        recall_client = RecallBotClient(
            api_key=config.recall_api_key,
            webhook_url=config.recall_webhook_public_url,
            region=config.recall_region,
            bot_name=config.recall_bot_name,
            language_code=config.recall_transcript_language,
            transport=config.recall_transport,
            ws_url=config.recall_ws_public_url,
            ws_events=config.recall_ws_events,
        )
        logger.info(
            "RecallBotClient 起動 (region=%s, source=%s, transport=%s)",
            config.recall_region, config.transcript_source, config.recall_transport,
        )

    # 4. create bot (orchestrator=None placeholder)
    bot = MeetingBot(
        cosmos_client=cosmos,
        graph_subscription=graph_sub,
        on_utterance=lambda utterance: asyncio.sleep(0),  # temporary placeholder
        recall_client=recall_client,
        recall_handler=recall_handler,
        transcript_source=config.transcript_source,
    )

    # 5. create app, adapter
    app, adapter = create_app_with_adapter(
        bot,
        config.microsoft_app_id,
        config.microsoft_app_password,
        recall_handler=recall_handler,
        recall_ws_handler=recall_ws_handler,
    )

    # 6. create orchestrator (needs adapter)
    orchestrator = Orchestrator(
        azure_openai_endpoint=config.azure_openai_endpoint,
        azure_openai_key=config.azure_openai_key,
        chat_deployment=config.azure_openai_deployment,
        embedding_deployment=config.azure_openai_embedding_deployment,
        search_endpoint=config.azure_search_endpoint,
        search_key=config.azure_search_key,
        search_index=config.azure_search_index,
        adapter=adapter,
        app_id=config.microsoft_app_id,
    )

    # 6. set orchestrator.set_cosmos(cosmos)
    orchestrator.set_cosmos(cosmos)

    # 7. set bot._orchestrator = orchestrator
    bot._orchestrator = orchestrator

    # 8. define on_utterance closure using orchestrator
    async def on_utterance(utterance: Utterance) -> None:
        logger.info(f"[発話受信] {utterance.speaker_name}: {utterance.text}")
        await orchestrator.process(utterance)

    # 8.b webhook dry-run モード (移行 Phase 5 で WS が主役のとき、二重処理回避用)
    async def _webhook_dry_run(utterance: Utterance) -> None:
        logger.info(
            "[webhook dry-run] meeting=%s speaker=%s text=%s",
            utterance.meeting_id, utterance.speaker_name, utterance.text,
        )

    # 9. inject on_utterance into bot & handlers
    bot._on_utterance = on_utterance
    if config.recall_webhook_dry_run:
        recall_handler.set_on_utterance(_webhook_dry_run)
    else:
        recall_handler.set_on_utterance(on_utterance)
    if recall_ws_handler is not None:
        recall_ws_handler.set_on_utterance(on_utterance)

    # 9.b （deprecated）旧ルータ。Phase 6 で削除。
    # 二重保存防止のため transport=websocket のときはマウントしない。
    if config.recall_transport in ("webhook", "both"):
        RecallWebhookRouter(orchestrator=orchestrator, cosmos=cosmos).register(app)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", config.port)
    await site.start()
    logger.info(f"Bot サーバー起動: port {config.port}")

    try:
        await asyncio.Event().wait()
    finally:
        if recall_client is not None:
            await recall_client.close()
        await cosmos.close()
        await runner.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
