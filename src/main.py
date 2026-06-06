"""Entry point for the offline Chinese transcription app."""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Ensure src/ is importable both in dev and inside the PyInstaller bundle.
sys.path.insert(0, str(Path(__file__).resolve().parent))

# Hard offline guarantee: the app must never touch the network.
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"


def main() -> None:
    from gui import App

    App().mainloop()


if __name__ == "__main__":
    main()
