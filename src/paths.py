"""Path resolution that works both in development and in a PyInstaller bundle."""

from __future__ import annotations

import sys
from pathlib import Path


def app_dir() -> Path:
    """Directory where the app lives.

    - PyInstaller onedir build: the directory containing the executable.
    - Development: the project root (parent of src/).
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def model_dir() -> Path:
    """Speech model folder shipped next to the executable."""
    return app_dir() / "model"


def llm_path() -> Path:
    """Local LLM (GGUF) used for offline summarization."""
    return app_dir() / "llm" / "qwen2.5-3b-instruct-q4_k_m.gguf"


def dictionary_path() -> Path:
    """User-editable dictionary file next to the executable."""
    return app_dir() / "dictionary.json"
