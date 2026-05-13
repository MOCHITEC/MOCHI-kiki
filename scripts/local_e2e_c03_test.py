# scripts/local_e2e_c03_test.py
"""
C-03 のローカル E2E テスト。
曖昧発言 → 確認メッセージ → 返信 → 整理文投稿 の一連フローを確認する。
Azure OpenAI への実際の接続が必要。
"""
import asyncio
import logging
from unittest.mock import AsyncMock, MagicMock
from src.config import Config
from src.models import Utterance
from src.kernel.orchestrator import Orchestrator

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


async def main():
    config = Config()

    mock_adapter = MagicMock()
    posted_messages = []

    async def mock_continue_conversation(ref, callback, app_id):
        mock_turn = MagicMock()
        captured = []

        async def mock_send(activity):
            captured.append(activity.text if hasattr(activity, "text") else str(activity))

        mock_turn.send_activity = mock_send
        await callback(mock_turn)
        for msg in captured:
            posted_messages.append({"ref": ref, "text": msg})

    mock_adapter.continue_conversation = mock_continue_conversation

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

    meeting_ref = MagicMock()
    speaker_ref = MagicMock()
    orchestrator.register_meeting("meet-local-001", meeting_ref)
    orchestrator.register_speaker("user-111", speaker_ref)

    # Step 1: 曖昧発言
    logger.info("=== Step 1: 曖昧発言 ===")
    utterance = Utterance.new(
        meeting_id="meet-local-001",
        speaker_id="user-111",
        speaker_name="田中 太郎",
        text="あれをやっておいて",
    )
    await orchestrator.process(utterance)
    await asyncio.sleep(0.5)

    logger.info(f"投稿数（確認メッセージ）: {len(posted_messages)}")
    for m in posted_messages:
        logger.info(f"  投稿先: {'speaker(1:1)' if m['ref'] is speaker_ref else 'meeting'}")
        logger.info(f"  内容: {m['text']}")

    # Step 2: 発言者が返信
    logger.info("\n=== Step 2: 発言者が返信 ===")
    before_count = len(posted_messages)
    await orchestrator.handle_clarification_reply(
        speaker_id="user-111",
        meeting_id="meet-local-001",
        reply_text="認証フローのレビュー（PR #42）のことです",
    )
    await asyncio.sleep(0.5)

    new_posts = posted_messages[before_count:]
    logger.info(f"新規投稿数（整理文）: {len(new_posts)}")
    for m in new_posts:
        logger.info(f"  投稿先: {'speaker(1:1)' if m['ref'] is speaker_ref else 'meeting'}")
        logger.info(f"  内容: {m['text']}")

    assert any("明確化" in m["text"] for m in new_posts), "整理文が会議チャットに投稿されていません"
    logger.info("\n✅ C-03 フロー確認完了")


if __name__ == "__main__":
    asyncio.run(main())
