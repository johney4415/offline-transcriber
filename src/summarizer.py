"""Offline summarization with a local LLM (llama-cpp-python + Qwen2.5-3B GGUF).

Runs entirely on CPU, no network. Long transcripts that exceed the model
context are handled with a map-reduce strategy: split into chunks, summarize
each, then summarize the combined chunk-summaries.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

# Context window we open. Qwen2.5 supports far more, but a larger window costs
# RAM (KV cache); 8192 tokens (~6000 Chinese chars) keeps an office PC happy.
N_CTX = 8192
# Reserve room for the prompt scaffolding + the generated answer.
MAX_INPUT_CHARS = 5000
CHUNK_OVERLAP_CHARS = 200

DEFAULT_INSTRUCTION = "請整理這段逐字稿的重點，並條列出待辦事項與決議。"

SYSTEM_PROMPT = (
    "你是專業的會議記錄助理。請用繁體中文、條理分明地整理使用者提供的逐字稿，"
    "忠實根據內容，不要捏造未提到的資訊。"
)


class LLMNotFoundError(Exception):
    pass


class Summarizer:
    def __init__(self, model_path: Path, n_threads: int = 0):
        if not model_path.exists():
            raise LLMNotFoundError(
                f"找不到語言模型：{model_path}\n"
                "請先在可連網的電腦執行 scripts/download_model.py，"
                "它會一併下載摘要用的模型。"
            )
        from llama_cpp import Llama  # heavy import, defer

        self._llm = Llama(
            model_path=str(model_path),
            n_ctx=N_CTX,
            n_threads=n_threads or None,
            verbose=False,
        )

    def _complete(
        self,
        instruction: str,
        content: str,
        on_token: Callable[[str], None] | None = None,
        should_cancel: Callable[[], bool] | None = None,
    ) -> str:
        """One chat completion, optionally streaming tokens to on_token."""
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"{instruction}\n\n逐字稿內容：\n{content}"},
        ]
        stream = self._llm.create_chat_completion(
            messages=messages,
            max_tokens=1024,
            temperature=0.3,
            stream=True,
        )
        parts: list[str] = []
        for chunk in stream:
            if should_cancel is not None and should_cancel():
                break
            delta = chunk["choices"][0]["delta"].get("content")
            if delta:
                parts.append(delta)
                if on_token is not None:
                    on_token(delta)
        return "".join(parts)

    @staticmethod
    def _chunk(text: str) -> list[str]:
        """Split a long transcript into overlapping chunks by character count."""
        if len(text) <= MAX_INPUT_CHARS:
            return [text]
        chunks: list[str] = []
        start = 0
        while start < len(text):
            end = start + MAX_INPUT_CHARS
            chunks.append(text[start:end])
            if end >= len(text):
                break
            start = end - CHUNK_OVERLAP_CHARS
        return chunks

    def summarize(
        self,
        transcript: str,
        instruction: str = DEFAULT_INSTRUCTION,
        on_token: Callable[[str], None] | None = None,
        on_status: Callable[[str], None] | None = None,
        should_cancel: Callable[[], bool] | None = None,
    ) -> str:
        """Summarize a transcript, map-reducing if it exceeds the context."""
        instruction = instruction.strip() or DEFAULT_INSTRUCTION
        chunks = self._chunk(transcript)

        if len(chunks) == 1:
            return self._complete(
                instruction, chunks[0], on_token=on_token, should_cancel=should_cancel
            )

        # Map: summarize each chunk (no streaming - it's intermediate output)
        partials: list[str] = []
        for i, chunk in enumerate(chunks, 1):
            if should_cancel is not None and should_cancel():
                return ""
            if on_status is not None:
                on_status(f"整理第 {i}/{len(chunks)} 段…")
            partials.append(
                self._complete(
                    "請摘要這一段逐字稿的重點（稍後會與其他段落合併）。",
                    chunk,
                    should_cancel=should_cancel,
                )
            )

        # Reduce: combine the partial summaries with the user's instruction
        if on_status is not None:
            on_status("彙整各段重點…")
        combined = "\n\n".join(f"【第 {i} 段重點】\n{p}" for i, p in enumerate(partials, 1))
        return self._complete(
            instruction, combined, on_token=on_token, should_cancel=should_cancel
        )
