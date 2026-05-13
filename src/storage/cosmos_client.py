from azure.cosmos.aio import CosmosClient as _AzureCosmosClient
from azure.cosmos import PartitionKey
from src.models import Utterance, Meeting


class CosmosClient:
    def __init__(self, endpoint: str, key: str, database_name: str) -> None:
        self._azure_client = _AzureCosmosClient(url=endpoint, credential=key)
        self._database_name = database_name
        self._utterances = None
        self._meetings = None

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

    async def save_utterance(self, utterance: Utterance) -> None:
        await self._utterances.upsert_item(utterance.to_dict())

    async def save_meeting(self, meeting: Meeting) -> None:
        await self._meetings.upsert_item(meeting.to_dict())

    async def close(self) -> None:
        await self._azure_client.close()
