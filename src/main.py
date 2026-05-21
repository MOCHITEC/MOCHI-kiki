import asyncio
import logging
from aiohttp import web
from src.config import Config
from src.storage.cosmos_client import CosmosClient
from src.transcript.graph_subscription import GraphTranscriptSubscription
from src.bot.teams_bot import MeetingBot
from src.bot.app import create_app_with_adapter
from src.kernel.orchestrator import Orchestrator
from src.models import Utterance

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

    # 2. create bot (orchestrator=None placeholder)
    bot = MeetingBot(
        cosmos_client=cosmos,
        graph_subscription=graph_sub,
        on_utterance=lambda utterance: asyncio.sleep(0),  # temporary placeholder
    )

    # 3. create app, adapter
    app, adapter = create_app_with_adapter(bot, config.microsoft_app_id, config.microsoft_app_password)

    # 4. create orchestrator (needs adapter)
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

    # 5. set orchestrator.set_cosmos(cosmos)
    orchestrator.set_cosmos(cosmos)

    # 6. set bot._orchestrator = orchestrator
    bot._orchestrator = orchestrator

    # 7. define on_utterance closure using orchestrator
    async def on_utterance(utterance: Utterance) -> None:
        logger.info(f"[発話受信] {utterance.speaker_name}: {utterance.text}")
        await orchestrator.process(utterance)

    # 8. set bot._on_utterance = on_utterance
    bot._on_utterance = on_utterance

    # 9. mount Recall.ai webhook route
    from src.api.recall_router import RecallWebhookRouter
    RecallWebhookRouter(orchestrator=orchestrator, cosmos=cosmos).register(app)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", config.port)
    await site.start()
    logger.info(f"Bot サーバー起動: port {config.port}")

    try:
        await asyncio.Event().wait()
    finally:
        await cosmos.close()
        await runner.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
