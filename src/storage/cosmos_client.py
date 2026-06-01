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
            )
            async for item in iterator:
                meeting_id = item.get("id")
                if isinstance(meeting_id, str) and meeting_id:
                    return meeting_id
        except Exception:
            # 例外時は呼び出し側で接続クローズ判断
            return None
        return None

    async def list_meetings_for_console(
        self, *, limit: int = 50, before: Optional[str] = None
    ) -> list[dict]:
        """started_at DESC で meetings を返す。before があれば started_at < before。"""
        limit = max(1, min(limit, 200))
        if before:
            query = (
                "SELECT * FROM c WHERE IS_DEFINED(c.started_at) "
                "AND c.started_at < @before "
                "ORDER BY c.started_at DESC OFFSET 0 LIMIT @limit"
            )
            params = [
                {"name": "@before", "value": before},
                {"name": "@limit", "value": limit},
            ]
        else:
            query = (
                "SELECT * FROM c WHERE IS_DEFINED(c.started_at) "
                "ORDER BY c.started_at DESC OFFSET 0 LIMIT @limit"
            )
            params = [{"name": "@limit", "value": limit}]
        items: list[dict] = []
        iterator = self._meetings.query_items(
            query=query, parameters=params
        )
        async for item in iterator:
            items.append(item)
        return items

    async def get_meeting_for_console(self, meeting_id: str) -> Optional[dict]:
        if not meeting_id:
            return None
        try:
            return await self._meetings.read_item(
                item=meeting_id, partition_key=meeting_id
            )
        except Exception:
            return None

    async def update_meeting_ended_at(
        self, meeting_id: str, ended_at_iso: str
    ) -> bool:
        item = await self.get_meeting_for_console(meeting_id)
        if not item:
            return False
        item["ended_at"] = ended_at_iso
        await self._meetings.upsert_item(item)
        return True

    async def find_meeting_id_by_recall_bot_id_any(
        self, recall_bot_id: str
    ) -> Optional[str]:
        """ended_at の有無に関わらず meeting_id を返す (退出処理用)。"""
        if not recall_bot_id:
            return None
        query = (
            "SELECT TOP 1 c.id FROM c WHERE c.recall_bot_id = @bot_id "
            "ORDER BY c.started_at DESC"
        )
        params = [{"name": "@bot_id", "value": recall_bot_id}]
        try:
            iterator = self._meetings.query_items(
                query=query, parameters=params
            )
            async for item in iterator:
                mid = item.get("id")
                if isinstance(mid, str) and mid:
                    return mid
        except Exception:
            return None
        return None

    async def list_utterances_for_meeting(
        self,
        meeting_id: str,
        *,
        since: Optional[str] = None,
        limit: int = 500,
    ) -> list[dict]:
        """timestamp ASC で utterances を返す。since があれば timestamp > since。"""
        if not meeting_id:
            return []
        limit = max(1, min(limit, 5000))
        if since:
            query = (
                "SELECT * FROM c WHERE c.meeting_id = @mid "
                "AND c.timestamp > @since "
                "ORDER BY c.timestamp ASC OFFSET 0 LIMIT @limit"
            )
            params = [
                {"name": "@mid", "value": meeting_id},
                {"name": "@since", "value": since},
                {"name": "@limit", "value": limit},
            ]
        else:
            query = (
                "SELECT * FROM c WHERE c.meeting_id = @mid "
                "ORDER BY c.timestamp ASC OFFSET 0 LIMIT @limit"
            )
            params = [
                {"name": "@mid", "value": meeting_id},
                {"name": "@limit", "value": limit},
            ]
        items: list[dict] = []
        iterator = self._utterances.query_items(
            query=query, parameters=params, partition_key=meeting_id
        )
        async for item in iterator:
            items.append(item)
        return items

    async def count_utterances_for_meeting(self, meeting_id: str) -> int:
        if not meeting_id:
            return 0
        query = "SELECT VALUE COUNT(1) FROM c WHERE c.meeting_id = @mid"
        params = [{"name": "@mid", "value": meeting_id}]
        try:
            iterator = self._utterances.query_items(
                query=query, parameters=params, partition_key=meeting_id
            )
            async for item in iterator:
                if isinstance(item, int):
                    return item
                if isinstance(item, dict):
                    for v in item.values():
                        if isinstance(v, int):
                            return v
        except Exception:
            return 0
        return 0

    async def upsert_minutes(
        self,
        meeting_id: str,
        markdown: str,
        utterance_count: int,
        updated_at_iso: str,
    ) -> bool:
        """meetings コンテナのレコードに議事録 Markdown を保存する。"""
        item = await self.get_meeting_for_console(meeting_id)
        if not item:
            return False
        item["minutes_markdown"] = markdown
        item["minutes_utterance_count"] = utterance_count
        item["minutes_updated_at"] = updated_at_iso
        await self._meetings.upsert_item(item)
        return True

    async def upsert_timeline_block(
        self,
        meeting_id: str,
        block: dict,
    ) -> bool:
        """meetings コンテナの timeline_blocks 配列に block を追加 / 更新する。
        block は {start_iso, end_iso, summary, utterance_count} を想定。
        既に同じ start_iso のブロックがあれば置換する。
        """
        item = await self.get_meeting_for_console(meeting_id)
        if not item:
            return False
        blocks = item.get("timeline_blocks") or []
        start = block.get("start_iso")
        replaced = False
        for i, b in enumerate(blocks):
            if b.get("start_iso") == start:
                blocks[i] = block
                replaced = True
                break
        if not replaced:
            blocks.append(block)
        # 時系列順を保証
        blocks.sort(key=lambda b: b.get("start_iso") or "")
        item["timeline_blocks"] = blocks
        await self._meetings.upsert_item(item)
        return True

    async def close(self) -> None:
        await self._azure_client.close()
