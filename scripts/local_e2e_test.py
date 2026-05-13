# scripts/local_e2e_test.py
"""
C-01 + C-02 のローカル E2E テスト。
モック発話ソースで会議シナリオを再現し、意図解析→RAG→回答生成のログを確認する。
Azure OpenAI と Azure AI Search への実際の接続が必要。
"""
import asyncio
import logging
import os
from unittest.mock import AsyncMock, MagicMock
from src.config import Config
from src.models import Utterance
from src.kernel.orchestrator import Orchestrator

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

TEST_UTTERANCES = [
    ("user-001", "田中 太郎", "了解しました。"),
    ("user-002", "鈴木 花子", "認証フローの仕様はどうなっていましたっけ？"),
    ("user-001", "田中 太郎", "SKU の定義を確認したいのですが。"),
    ("user-003", "佐藤 次郎", "ありがとうございます。"),
]


async def main():
    config = Config()

    # Adapter と app_id はモック（実際の Teams 投稿はしない）
    mock_adapter = MagicMock()
    mock_adapter.continue_conversation = AsyncMock()

    orchestrator = Orchestrator(
        azure_openai_endpoint=config.azure_openai_endpoint,
        azure_openai_key=config.azure_openai_key,
        chat_deployment=config.azure_openai_deployment,
        embedding_deployment=config.azure_openai_embedding_deployment,
        search_endpoint=config.azure_search_endpoint,
        search_key=config.azure_search_key,
        search_index=config.azure_search_index,
        adapter=mock_adapter,
        app_id=config.microsoft_app_id,
    )

    # 会議の ConversationReference をモック登録
    mock_ref = MagicMock()
    orchestrator.register_meeting("meet-local-001", mock_ref)

    for speaker_id, speaker_name, text in TEST_UTTERANCES:
        utterance = Utterance.new(
            meeting_id="meet-local-001",
            speaker_id=speaker_id,
            speaker_name=speaker_name,
            text=text,
        )
        logger.info(f"--- 発話: [{speaker_name}] {text}")
        await orchestrator.process(utterance)

    # 投稿された内容を確認
    calls = mock_adapter.continue_conversation.call_args_list
    logger.info(f"\n=== チャット投稿数: {len(calls)} ===")
    for i, call in enumerate(calls, 1):
        # callback を実行して投稿内容を取り出す
        logger.info(f"投稿 {i}: (continue_conversation が呼ばれました)")


if __name__ == "__main__":
    asyncio.run(main())
