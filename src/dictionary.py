"""User dictionary: load/save dictionary.json and build the Whisper initial prompt.

The dictionary file lives next to the executable so users can edit it either
through the GUI or directly with a text editor.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from pathlib import Path


@dataclass
class WordEntry:
    """A correct word (e.g. a person's name) used for homophone correction.

    Attributes:
        word: The correct text, e.g. "王小明".
        enabled: Whether homophone correction applies for this entry.
        use_prompt: Whether to feed this word into Whisper's initial prompt.
        fuzzy: Whether fuzzy pinyin pairs (zh/z, l/n, in/ing, ...) apply.
    """

    word: str
    enabled: bool = True
    use_prompt: bool = True
    fuzzy: bool = False


@dataclass
class ReplacementRule:
    """A literal find -> replace rule applied as the final pass."""

    src: str
    dst: str
    enabled: bool = True


@dataclass
class UserDictionary:
    words: list[WordEntry] = field(default_factory=list)
    replacements: list[ReplacementRule] = field(default_factory=list)

    # -- persistence ---------------------------------------------------

    @classmethod
    def load(cls, path: Path) -> "UserDictionary":
        if not path.exists():
            return cls()
        data = json.loads(path.read_text(encoding="utf-8"))
        words = [
            WordEntry(
                word=w["word"],
                enabled=w.get("enabled", True),
                use_prompt=w.get("use_prompt", True),
                fuzzy=w.get("fuzzy", False),
            )
            for w in data.get("words", [])
            if w.get("word")
        ]
        replacements = [
            ReplacementRule(
                src=r["from"],
                dst=r.get("to", ""),
                enabled=r.get("enabled", True),
            )
            for r in data.get("replacements", [])
            if r.get("from")
        ]
        return cls(words=words, replacements=replacements)

    def save(self, path: Path) -> None:
        data = {
            "words": [asdict(w) for w in self.words],
            "replacements": [
                {"from": r.src, "to": r.dst, "enabled": r.enabled}
                for r in self.replacements
            ],
        }
        path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    # -- prompt building -----------------------------------------------

    def build_initial_prompt(self, count_tokens, max_tokens: int = 224) -> str:
        """Build the Whisper initial prompt from prompt-enabled words.

        Whisper keeps only the LAST ``max_tokens`` tokens of the prompt, so
        dictionary words go after the base sentence. When over budget we drop
        words from the FRONT of the list: trailing tokens survive Whisper's
        keep-last truncation, so later entries are effectively higher priority.

        Args:
            count_tokens: Callable[[str], int] using the real model tokenizer.
            max_tokens: Whisper's effective prompt budget (224).
        """
        base = "以下是繁體中文的逐字稿。"
        words = [w.word for w in self.words if w.enabled and w.use_prompt]
        if not words:
            return base

        # Keep as many words as fit within the budget. Words near the END of
        # the prompt survive Whisper's keep-last-224 truncation, so we drop
        # from the front of the list when over budget.
        while words:
            prompt = base + "提及的詞彙：" + "、".join(words) + "。"
            if count_tokens(prompt) <= max_tokens:
                return prompt
            words = words[1:]
        return base
