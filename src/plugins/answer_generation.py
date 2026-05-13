# src/plugins/answer_generation.py
from typing import List

import semantic_kernel as sk
from semantic_kernel.functions import KernelArguments

from src.plugins.rag_search import SearchResult


ANSWER_PROMPT = """
あなたは会議中に仕様情報を提供する AI アシスタントです。
以下の会議での発言と、社内ドキュメントから取得した関連情報をもとに、
200 文字以内で簡潔に回答してください。

発言: {{$utterance}}

関連ドキュメント:
{{$context}}

回答は **[仕様補完]** というプレフィックスをつけずに、事実のみを簡潔に述べてください。
200 文字を超えた場合は最も重要な情報のみを残して切り詰めてください。
"""


class AnswerGenerationPlugin:
    def __init__(self, kernel: sk.Kernel) -> None:
        self._kernel = kernel
        self._function = kernel.add_function(
            plugin_name="AnswerGeneration",
            function_name="generate",
            prompt=ANSWER_PROMPT,
        )

    async def generate(self, utterance: str, search_results: List[SearchResult]) -> str:
        context = "\n---\n".join(
            f"【{r.title}】\n{r.content}" for r in search_results
        )
        result = await self._kernel.invoke(
            self._function,
            KernelArguments(utterance=utterance, context=context),
        )
        text = str(result).strip()
        return text[:200] if len(text) > 200 else text
