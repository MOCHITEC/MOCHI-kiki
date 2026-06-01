# src/plugins/minutes_generator.py
"""
会議の発話群を構造化議事録 (Markdown) に整形する。
業務用・丁寧な文体。議題 / 決定事項 / TODO / 質疑応答 セクション。
"""
from __future__ import annotations

import logging
from typing import List

import semantic_kernel as sk
from semantic_kernel.functions import KernelArguments

logger = logging.getLogger(__name__)


_PROMPT = """あなたは熟練の議事録作成者です。Teams 会議の生発話 (時系列) を読み、業務用の議事録を Markdown で作成してください。

# 出力フォーマット (必ずこの構造で)

## 議題
- 議論された主要な話題を箇条書き (2〜5 項目)。重要な順に。

## 決定事項
- 会議内で明示的に合意された結論や方針を箇条書き。
- なければ「特に明示的な決定事項はなし」。

## TODO
- [ ] 担当者が明示されている場合は「<担当者>: <タスク>」、不明なら「<タスク>」。
- 期限が出ていれば末尾に `（期限: ...）`。
- なければ「特になし」。

## 質疑応答
- 出た質問とそれに対する回答 (会議内で答えがあったもの) をペアで列挙。
- フォーマット: **Q.** <質問>  **A.** <回答>
- 未解決の質問は **Q.** <質問>  **A.** *未回答* と記す。

# 注意
- 文末は「である」「した」「確認した」など事実ベースの体言止め寄り。
- 雑談・相づち (「うんうん」「えーと」など) は省く。
- 発言者名がついている場合は質疑応答だけ「Q. (発言者) ...」のように残す。
- 出力は Markdown のみ。前置きの説明文や挨拶は不要。

# 会議の発話 (時系列)
{{$transcript}}
"""


class MinutesGeneratorPlugin:
    def __init__(self, kernel: sk.Kernel) -> None:
        self._kernel = kernel
        self._function = kernel.add_function(
            plugin_name="MinutesGenerator",
            function_name="generate",
            prompt=_PROMPT,
        )

    async def generate(self, utterances: List[dict]) -> str:
        """utterance dict のリストから議事録 Markdown を生成する。
        utterance dict は少なくとも text, speaker_name, timestamp を持つ想定。
        """
        if not utterances:
            return ""

        # 整形済み発話テキストに変換 (長すぎる場合は古いものから切り詰める)
        lines: list[str] = []
        for u in utterances:
            ts = (u.get("timestamp") or "")[11:19]
            speaker = u.get("speaker_name") or u.get("speaker") or "不明"
            text = (u.get("text") or "").strip()
            if not text:
                continue
            lines.append(f"[{ts}] {speaker}: {text}")

        transcript = "\n".join(lines)
        # GPT-4o context window 128k だが、prompt 全体で 16k 程度に抑える
        max_chars = 32000
        if len(transcript) > max_chars:
            transcript = transcript[-max_chars:]
            transcript = "...(古い発話は省略)...\n" + transcript

        try:
            result = await self._kernel.invoke(
                self._function,
                KernelArguments(transcript=transcript),
            )
            return str(result).strip()
        except Exception:
            logger.exception("MinutesGenerator.generate failed")
            return ""
