"""One-time model download script.

Run this ONCE on a machine WITH internet access, then copy the resulting
``model/`` folder next to the app executable. The app itself never touches
the network (it loads the model with ``local_files_only=True`` and quantizes
to int8 in memory at load time).

Usage:
    python scripts/download_model.py [output_dir]

Default output_dir is ``model/`` in the project root.
"""

from __future__ import annotations

import sys
from pathlib import Path

from huggingface_hub import snapshot_download

MODEL_REPO = "mobiuslabsgmbh/faster-whisper-large-v3-turbo"

# Only the files faster-whisper actually needs at runtime.
ALLOW_PATTERNS = [
    "model.bin",
    "config.json",
    "tokenizer.json",
    "vocabulary.*",
    "preprocessor_config.json",
]


def main() -> None:
    out_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent / "model"
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"Downloading {MODEL_REPO} to {out_dir} ...")
    snapshot_download(
        repo_id=MODEL_REPO,
        local_dir=str(out_dir),
        allow_patterns=ALLOW_PATTERNS,
    )
    print("Done. Copy this folder next to the app executable as 'model/'.")


if __name__ == "__main__":
    main()
