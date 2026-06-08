"""One-time model download script.

Run this ONCE on a machine WITH internet access, then copy the resulting
``model/`` and ``llm/`` folders next to the app executable. The app itself
never touches the network (speech model loads with ``local_files_only=True``;
the summarization LLM loads from a local GGUF file).

Usage:
    python scripts/download_model.py [base_dir]

Default base_dir is the project root (creates ``model/`` and ``llm/`` in it).
"""

from __future__ import annotations

import sys
from pathlib import Path

from huggingface_hub import hf_hub_download, snapshot_download

SPEECH_REPO = "mobiuslabsgmbh/faster-whisper-large-v3-turbo"
# Only the files faster-whisper actually needs at runtime.
SPEECH_PATTERNS = [
    "model.bin",
    "config.json",
    "tokenizer.json",
    "vocabulary.*",
    "preprocessor_config.json",
]

LLM_REPO = "Qwen/Qwen2.5-3B-Instruct-GGUF"
LLM_FILE = "qwen2.5-3b-instruct-q4_k_m.gguf"


def main() -> None:
    base = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent
    # Back-compat: if the arg points at a 'model' dir, treat its parent as base.
    if base.name == "model":
        base = base.parent
    base.mkdir(parents=True, exist_ok=True)

    speech_dir = base / "model"
    speech_dir.mkdir(parents=True, exist_ok=True)
    print(f"Downloading speech model {SPEECH_REPO} to {speech_dir} ...")
    snapshot_download(
        repo_id=SPEECH_REPO,
        local_dir=str(speech_dir),
        allow_patterns=SPEECH_PATTERNS,
    )

    llm_dir = base / "llm"
    llm_dir.mkdir(parents=True, exist_ok=True)
    print(f"Downloading summarization model {LLM_REPO}/{LLM_FILE} to {llm_dir} ...")
    hf_hub_download(repo_id=LLM_REPO, filename=LLM_FILE, local_dir=str(llm_dir))

    print("Done. Copy the 'model' and 'llm' folders next to the app executable.")


if __name__ == "__main__":
    main()
