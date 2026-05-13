# src/transcript/mock_source.py
import asyncio
from src.transcript.base import UtteranceSource
from src.models import Utterance
from typing import Callable, Awaitable, List


class MockUtteranceSource(UtteranceSource):
    """テスト・デモ用のモック発話ソース。事前定義した発話リストを順番に emit する。"""

    def __init__(
        self,
        utterances: List[Utterance],
        on_utterance: Callable[[Utterance], Awaitable[None]],
        interval_seconds: float = 0.1,
    ) -> None:
        self._utterances = utterances
        self._on_utterance = on_utterance
        self._interval = interval_seconds
        self._task = None

    async def start(self, meeting_id: str) -> None:
        self._task = asyncio.create_task(self._emit_loop())

    async def _emit_loop(self) -> None:
        for u in self._utterances:
            await self._on_utterance(u)
            await asyncio.sleep(self._interval)

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
