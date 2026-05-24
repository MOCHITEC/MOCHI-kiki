from typing import Optional
from azure.cosmos.aio import CosmosClient as _AzureCosmosClient
from azure.cosmos import PartitionKey
from src.models import Utterance, Meeting


class CosmosClient:
    def __init__(self, endpoint: str, key: str, database_name: str) -> None:
        self._azure_client = _AzureCosmosClient(url=endpoint, credential=key)
        self._database_name = database_name
        self._utterances = None
        self._meetings = None
        self._clarification_sessions = None

    async def initialize(self) -> None:
        """DB・コンテナが存在しない場合は作成する。"""
        db = await self._azure_client.create_database_if_not_exists(self._database_name)
        self._utterances = await db.create_container_if_not_exists(
            id="utterances",
            partition_key=PartitionKey(path="/meeting_id"),
        )
        self._meetings = await db.create_container_if_not_exists(
            id="meetings",
            partition_key=PartitionKey(path="/id"),
        )
        self._clarification_sessions = await db.create_container_if_not_exists(
            id="clarification_sessions",
            partition_key=PartitionKey(path="/meeting_id"),
        )

    async def save_utterance(self, utterance: Utterance) -> None:
        await self._utterances.upsert_item(utterance.to_dict())

    async def save_meeting(self, meeting: Meeting) -> None:
        await self._meetings.upsert_item(meeting.to_dict())

    async def save_clarification_session(self, session: "ClarificationSession") -> None:
        from src.kernel.clarification_session import ClarificationSession
        await self._clarification_sessions.upsert_item(session.to_dict())

    async def get_clarification_session(
        self, session_id: str, meeting_id: str
    ) -> Optional[dict]:
        try:
            item = await self._clarification_sessions.read_item(
                item=session_id, partition_key=meeting_id
            )
            return item
        except Exception:
            return None

    async def find_meeting_id_by_recall_bot_id(self, recall_bot_id: str) -> Optional[str]:
        """
        Recall bot.id から meeting_id を逆引きする。
        WebSocket 経路で bot 投入と接続受信が別レプリカに割り振られた場合の
        bot↔meeting 解決フォールバック。
        """
        if not recall_bot_id:
            return None
        query = (
            "SELECT TOP 1 c.id FROM c WHERE c.recall_bot_id = @bot_id "
            "AND (NOT IS_DEFINED(c.ended_at) OR c.ended_at = null)"
        )
        params = [{"name": "@bot_id", "value": recall_bot_id}]
        try:
            iterator = self._meetings.query_items(
                query=query,
                parameters=params,
                enable_cross_partition_query=True,
            )
            async for item in iterator:
                meeting_id = item.get("id")
                if isinstance(meeting_id, str) and meeting_id:
                    return meeting_id
        except Exception:
            # 例外時は呼び出し側で接続クローズ判断
            return None
        return None

    async def close(self) -> None:
        await self._azure_client.close()
