# src/transcript/base.py
from abc import ABC, abstractmethod
from src.models import Utterance


class UtteranceSource(ABC):
    """会議の発話を非同期で提供する抽象インターフェース。"""

    @abstractmethod
    async def start(self, meeting_id: str) -> None:
        """発話の受信を開始する。"""
        ...

    @abstractmethod
    async def stop(self) -> None:
        """受信を停止し、リソースを解放する。"""
        ...
