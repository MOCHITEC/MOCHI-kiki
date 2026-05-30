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
from src.api.console_router import build_console_router_from_env
from src.api.static_router import register_static_router

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 固定値: env 化する理由が無いもの
_RECALL_BOT_NAME = "MOCHI-kiki"
_RECALL_TRANSCRIPT_LANGUAGE = "ja"
_RECALL_WS_EVENTS = ("audio_mixed_raw.data", "transcript.data")


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
        )
        logger.info(
            "RecallWsHandler 起動 (audio_sink=%s, events=%s)",
            config.recall_audio_sink, _RECALL_WS_EVENTS,
        )

    # 3. Recall bot client (transcript_source が recall/both のときのみ)
    recall_client: Optional[RecallBotClient] = None
    if config.transcript_source in ("recall", "both"):
        recall_client = RecallBotClient(
            api_key=config.recall_api_key,
            webhook_url=config.recall_webhook_public_url,
            region=config.recall_region,
            bot_name=_RECALL_BOT_NAME,
            language_code=_RECALL_TRANSCRIPT_LANGUAGE,
            transport=config.recall_transport,
            ws_url=config.recall_ws_public_url,
            ws_events=_RECALL_WS_EVENTS,
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

    # 9. inject on_utterance into bot & handlers
    bot._on_utterance = on_utterance
    recall_handler.set_on_utterance(on_utterance)
    if recall_ws_handler is not None:
        recall_ws_handler.set_on_utterance(on_utterance)

    # 9.b （deprecated）旧ルータ。Phase 6 で削除。
    # 二重保存防止のため transport=websocket のときはマウントしない。
    if config.recall_transport in ("webhook", "both"):
        RecallWebhookRouter(orchestrator=orchestrator, cosmos=cosmos).register(app)

    # 9.c 管理コンソール (frontend-bot-console) 用ルータ
    if config.console_enabled:
        console = build_console_router_from_env(
            cosmos=cosmos,
            recall_client=recall_client,
            username=config.console_username,  # type: ignore[arg-type]
            password_hash=config.console_password_hash,  # type: ignore[arg-type]
            jwt_secret=config.console_jwt_secret,  # type: ignore[arg-type]
        )
        console.register(app)
        logger.info(
            "管理コンソール /api/console/* 有効化 (recall=%s)",
            "yes" if recall_client is not None else "no",
        )

    # 9.d frontend static 配信 (Next.js export が同梱されていれば)
    register_static_router(app)

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
