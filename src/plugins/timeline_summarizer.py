# src/plugins/timeline_summarizer.py
"""
会議の発話を一定時間単位 (例: 5 分) のブロックに区切り、各ブロックを要約する。
ライブで時間軸に沿って進捗を追えるサマリ。
"""
from __future__ import annotations

import logging
from typing import List

import semantic_kernel as sk
from semantic_kernel.functions import KernelArguments

logger = logging.getLogger(__name__)


_PROMPT = """あなたは熟練の議事録作成者です。Teams 会議のある時間帯 (約 5 分) の発話を読み、その間に議論された内容を 1〜3 行 (合計 150 文字以内) で簡潔にまとめてください。

# 注意
- 雑談や相づちは省く。
- 「である」「した」など事実ベースの簡潔な文体。
- 「議論があった」「言及された」のような曖昧表現より、具体的な話題を挙げる。
- 出力は要約本文のみ。前置きや見出しは不要。

# この時間帯の発話
{{$transcript}}
"""


class TimelineSummarizerPlugin:
    def __init__(self, kernel: sk.Kernel) -> None:
        self._kernel = kernel
        self._function = kernel.add_function(
            plugin_name="TimelineSummarizer",
            function_name="summarize_block",
            prompt=_PROMPT,
        )

    async def summarize_block(self, utterances: List[dict]) -> str:
        """ある時間ブロックの utterance 群を 150 字以内で要約する。"""
        if not utterances:
            return ""

        lines: list[str] = []
        for u in utterances:
            speaker = u.get("speaker_name") or u.get("speaker") or "不明"
            text = (u.get("text") or "").strip()
            if not text:
                continue
            lines.append(f"{speaker}: {text}")

        transcript = "\n".join(lines)
        if len(transcript) > 8000:
            transcript = transcript[-8000:]

        try:
            result = await self._kernel.invoke(
                self._function,
                KernelArguments(transcript=transcript),
            )
            return str(result).strip()
        except Exception:
            logger.exception("TimelineSummarizer.summarize_block failed")
            return ""
