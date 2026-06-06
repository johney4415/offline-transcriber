"""faster-whisper wrapper: strictly-local model loading and progress reporting."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterator


@dataclass
class Segment:
    start: float
    end: float
    text: str


class ModelNotFoundError(Exception):
    pass


class Transcriber:
    def __init__(self, model_dir: Path, cpu_threads: int = 0):
        if not (model_dir / "model.bin").exists():
            raise ModelNotFoundError(
                f"找不到模型檔：{model_dir}/model.bin\n"
                "請先在可連網的電腦執行 scripts/download_model.py，"
                "並將產生的 model 資料夾放到程式旁邊。"
            )
        # Belt and braces: even though we load from a local path with
        # local_files_only, force HF hub offline so nothing ever dials out.
        os.environ.setdefault("HF_HUB_OFFLINE", "1")

        from faster_whisper import WhisperModel  # heavy import, defer

        self._model = WhisperModel(
            str(model_dir),
            device="cpu",
            compute_type="int8",
            cpu_threads=cpu_threads,
            local_files_only=True,
        )

    def count_tokens(self, text: str) -> int:
        return len(self._model.hf_tokenizer.encode(text).ids)

    def transcribe(
        self,
        audio_path: Path,
        initial_prompt: str | None = None,
        beam_size: int = 2,
        on_progress: Callable[[float], None] | None = None,
        should_cancel: Callable[[], bool] | None = None,
    ) -> Iterator[Segment]:
        """Yield segments lazily; on_progress receives a 0..1 ratio."""
        segments, info = self._model.transcribe(
            str(audio_path),
            language="zh",
            beam_size=beam_size,
            initial_prompt=initial_prompt,
            condition_on_previous_text=False,
            vad_filter=True,
        )
        duration = max(info.duration or 0.0, 0.001)
        for seg in segments:
            if should_cancel is not None and should_cancel():
                return
            if on_progress is not None:
                on_progress(min(seg.end / duration, 1.0))
            yield Segment(start=seg.start, end=seg.end, text=seg.text.strip())


def format_srt(segments: list[Segment]) -> str:
    """Render segments as an SRT subtitle file."""

    def ts(seconds: float) -> str:
        ms = int(round(seconds * 1000))
        h, rem = divmod(ms, 3600_000)
        m, rem = divmod(rem, 60_000)
        s, ms = divmod(rem, 1000)
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

    lines: list[str] = []
    for i, seg in enumerate(segments, 1):
        lines.append(str(i))
        lines.append(f"{ts(seg.start)} --> {ts(seg.end)}")
        lines.append(seg.text)
        lines.append("")
    return "\n".join(lines)
