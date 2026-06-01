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

# 絶対のルール (最優先、違反しないこと)
- **発話に登場しない人物・組織・数値・期限・出来事を絶対に追加しないこと**。
  「鈴木さん」「先週の会議で...」など、入力に無い情報を補完するのは禁止。
  根拠が無い項目は書かない。
- **出力は素の Markdown のみ**。先頭に ```markdown や末尾の ``` で囲わない。前置き・挨拶・要約コメントも書かない。
- 発話の発言者名は厳密に入力にあるものだけを使うこと。

# 出力フォーマット (必ずこの構造で)

## 議題
- 実際に議論された主要な話題を箇条書き (2〜5 項目程度)。発話に無い議題を捏造しない。

## 決定事項
- 会議内で明示的に合意された結論や方針を箇条書き。
- 明示的合意が無ければ単に「特になし」とだけ書く。

## TODO
- [ ] 担当者が発話で明示されている場合は「<担当者>: <タスク>」、不明なら「<タスク>」。
- 期限が発話で出ていれば末尾に `（期限: ...）`。
- 無ければ「特になし」とだけ書く。

## 質疑応答
- 発話で実際に出た質問と、会議内で答えがあったものをペアで列挙。
- フォーマット: **Q. (<発言者>)** <質問>  **A. (<回答者>)** <回答>
- 未回答の質問は **A.** *未回答*。
- 質疑応答が無ければ「特になし」とだけ書く。

# 文体
- 「である」「した」「確認した」など事実ベースの簡潔な業務文体。
- 相づち・言い直し・雑談 (「えーと」「うんうん」など) は省く。

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
            text = str(result).strip()
            # GPT が ```markdown ... ``` で囲んでも除去
            if text.startswith("```"):
                first_nl = text.find("\n")
                if first_nl > 0:
                    text = text[first_nl + 1 :]
                if text.endswith("```"):
                    text = text[:-3].rstrip()
            return text.strip()
        except Exception:
            logger.exception("MinutesGenerator.generate failed")
            return ""
