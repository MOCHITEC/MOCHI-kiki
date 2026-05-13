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

    async def close(self) -> None:
        await self._azure_client.close()
