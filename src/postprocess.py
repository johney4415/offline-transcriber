"""Post-processing pipeline: OpenCC (s2twp) -> homophone correction -> literal replace.

Pass order rationale:
  1. OpenCC first normalizes everything to Traditional Chinese (Taiwan), so
     pinyin matching operates on a consistent script.
  2. Homophone correction replaces substrings whose pinyin matches a
     dictionary word (e.g. 汪曉明 -> 王小明).
  3. Literal replacement rules run LAST as the user's authoritative override.
"""

from __future__ import annotations

import re
from functools import lru_cache

from opencc import OpenCC
from pypinyin import pinyin, Style

from dictionary import UserDictionary, WordEntry

_HAN_RE = re.compile(r"[㐀-䶿一-鿿豈-﫿]")

# Fuzzy pinyin normalization for common Taiwan-accent confusions.
# Initials are collapsed (zh->z, ch->c, sh->s, n->l) and finals merged
# (ing->in, eng->en, ang->an is NOT included - too aggressive).
_FUZZY_INITIALS = {"zh": "z", "ch": "c", "sh": "s", "n": "l"}
_FUZZY_FINAL_SUFFIXES = [("ing", "in"), ("eng", "en")]


def _is_han(ch: str) -> bool:
    return bool(_HAN_RE.match(ch))


def _fuzzy_normalize(syllable: str) -> str:
    """Collapse fuzzy pairs to a canonical form, e.g. zhang -> zang,
    ling -> lin, neng -> len."""
    s = syllable
    for src, dst in _FUZZY_INITIALS.items():
        if s.startswith(src):
            s = dst + s[len(src):]
            break
    for src, dst in _FUZZY_FINAL_SUFFIXES:
        if s.endswith(src):
            s = s[: -len(src)] + dst
            break
    return s


@lru_cache(maxsize=4096)
def _char_readings(ch: str) -> frozenset[str]:
    """All tone-less pinyin readings of a single Han character."""
    try:
        readings = pinyin(ch, style=Style.NORMAL, heteronym=True, errors="ignore")
    except Exception:
        return frozenset()
    if not readings or not readings[0]:
        return frozenset()
    return frozenset(r for r in readings[0] if r)


def _word_reading_sets(word: str, fuzzy: bool) -> list[frozenset[str]]:
    """Per-character reading sets for a dictionary word (precomputed once)."""
    sets: list[frozenset[str]] = []
    for ch in word:
        readings = _char_readings(ch)
        if fuzzy:
            readings = frozenset(_fuzzy_normalize(r) for r in readings)
        sets.append(readings)
    return sets


class HomophoneCorrector:
    """Replaces transcript substrings whose pinyin matches dictionary words.

    Matching policy: per character position the candidate-reading sets must
    intersect (heteronym-aware). Longest dictionary words are tried first,
    scanning left to right; replaced spans never overlap. Windows only cover
    consecutive Han characters - they never span punctuation or spaces.
    """

    def __init__(self, entries: list[WordEntry]):
        active = [e for e in entries if e.enabled and len(e.word) >= 2]
        # Longest first so e.g. 王小明 wins over 王小 at the same position.
        active.sort(key=lambda e: len(e.word), reverse=True)
        self._targets = [
            (e.word, _word_reading_sets(e.word, e.fuzzy), e.fuzzy) for e in active
        ]

    def correct(self, text: str) -> str:
        if not self._targets or not text:
            return text

        chars = list(text)
        # Per-char readings, both exact and fuzzy-normalized (None for non-Han).
        exact: list[frozenset[str] | None] = []
        fuzzy: list[frozenset[str] | None] = []
        for ch in chars:
            if _is_han(ch):
                readings = _char_readings(ch)
                exact.append(readings)
                fuzzy.append(frozenset(_fuzzy_normalize(r) for r in readings))
            else:
                exact.append(None)
                fuzzy.append(None)

        consumed = [False] * len(chars)
        replacements: list[tuple[int, int, str]] = []  # (start, end, word)

        for word, word_sets, use_fuzzy in self._targets:
            n = len(word_sets)
            transcript_sets = fuzzy if use_fuzzy else exact
            i = 0
            while i + n <= len(chars):
                if text[i : i + n] == word:
                    # Already correct - consume so shorter words can't clobber it.
                    if not any(consumed[i : i + n]):
                        for j in range(i, i + n):
                            consumed[j] = True
                    i += n
                    continue
                window = transcript_sets[i : i + n]
                if not any(consumed[i : i + n]) and all(
                    w is not None and (w & t) for w, t in zip(window, word_sets)
                ):
                    replacements.append((i, i + n, word))
                    for j in range(i, i + n):
                        consumed[j] = True
                    i += n
                else:
                    i += 1

        for start, end, word in sorted(replacements, reverse=True):
            chars[start:end] = list(word)
        return "".join(chars)


class PostProcessor:
    """Full pipeline applied to each transcript segment."""

    def __init__(self, dictionary: UserDictionary, to_taiwan: bool = True):
        self._opencc = OpenCC("s2twp") if to_taiwan else None
        self._corrector = HomophoneCorrector(dictionary.words)
        self._rules = [r for r in dictionary.replacements if r.enabled and r.src]

    def process(self, text: str) -> str:
        if self._opencc is not None:
            text = self._opencc.convert(text)
        text = self._corrector.correct(text)
        for rule in self._rules:
            text = text.replace(rule.src, rule.dst)
        return text
