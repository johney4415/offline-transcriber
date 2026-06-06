"""Learn dictionary rules from user corrections - fully offline.

Compares the original transcript with the user-corrected version (difflib,
pure local computation), extracts changed spans, and classifies each change:

- Same length, all Han, pinyin matches per char  -> homophone word suggestion
  (add the corrected word to the words table, e.g. 汪曉明 -> 王小明)
- Pinyin matches only after fuzzy normalization  -> homophone with fuzzy=True
- Anything else                                  -> literal replacement rule

The user reviews suggestions in the GUI before anything is written to
dictionary.json, so one-off edits don't become permanent rules.
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass

from dictionary import ReplacementRule, UserDictionary, WordEntry
from postprocess import _char_readings, _fuzzy_normalize, _is_han

# Edits longer than this are likely rephrasing, not term fixes - skip them.
MAX_SPAN = 8
# Homophone dictionary words work best short (names, jargon).
MAX_WORD_LEN = 4


@dataclass
class Suggestion:
    kind: str  # "word" | "rule"
    src: str  # original (wrong) text
    dst: str  # corrected text
    fuzzy: bool = False
    # Pre-checked in the review dialog. The span-expanded variant of a
    # homophone fix is preselected; its unexpanded sibling is not.
    preselected: bool = True

    def describe(self) -> str:
        if self.kind == "word":
            label = "詞彙（同音字修正）"
            if self.fuzzy:
                label = "詞彙（同音字修正・模糊音）"
        else:
            label = "取代規則"
        return label


def _pinyin_relation(src: str, dst: str) -> str | None:
    """Return 'exact'/'fuzzy' if src and dst are per-char homophones, else None."""
    if len(src) != len(dst):
        return None
    if not all(_is_han(c) for c in src + dst):
        return None
    exact = True
    for a, b in zip(src, dst):
        ra, rb = _char_readings(a), _char_readings(b)
        if not ra or not rb:
            return None
        if ra & rb:
            continue
        exact = False
        fa = {_fuzzy_normalize(r) for r in ra}
        fb = {_fuzzy_normalize(r) for r in rb}
        if not (fa & fb):
            return None
    return "exact" if exact else "fuzzy"


def _expand_span(
    original: str, corrected: str, a0: int, a1: int, b0: int, b1: int
) -> tuple[str, str]:
    """Grow a replaced span over adjacent identical Han chars.

    A diff of 汪曉明 -> 王小明 only marks 汪曉 -> 王小 (明 is common), but the
    dictionary entry should be the whole name. Word boundaries are unknowable
    from pinyin alone, so expansion is conservative: a single-char replacement
    (middle of a name, 曉->小) may extend one char on BOTH sides; a longer
    replacement extends one char on ONE side only (right preferred). The
    caller also keeps the unexpanded span as an alternative suggestion.
    """
    span = b1 - b0
    can_right = (
        a1 < len(original)
        and b1 < len(corrected)
        and original[a1] == corrected[b1]
        and _is_han(original[a1])
    )
    can_left = (
        a0 > 0
        and b0 > 0
        and original[a0 - 1] == corrected[b0 - 1]
        and _is_han(original[a0 - 1])
    )
    budget = 2 if span == 1 else 1
    if can_right and budget and b1 - b0 < MAX_WORD_LEN:
        a1 += 1
        b1 += 1
        budget -= 1
    if can_left and budget and b1 - b0 < MAX_WORD_LEN:
        a0 -= 1
        b0 -= 1
    return original[a0:a1], corrected[b0:b1]


def extract_suggestions(
    original: str, corrected: str, dictionary: UserDictionary
) -> list[Suggestion]:
    """Diff original vs corrected text and propose dictionary additions."""
    known_words = {w.word for w in dictionary.words}
    known_rules = {(r.src, r.dst) for r in dictionary.replacements}

    suggestions: list[Suggestion] = []
    seen: set[tuple[str, str, str]] = set()

    matcher = difflib.SequenceMatcher(None, original, corrected, autojunk=False)
    for tag, a0, a1, b0, b1 in matcher.get_opcodes():
        if tag != "replace":
            continue  # pure insert/delete is rephrasing, not a term fix
        src, dst = original[a0:a1].strip(), corrected[b0:b1].strip()
        if not src or not dst or src == dst:
            continue
        if len(src) > MAX_SPAN or len(dst) > MAX_SPAN:
            continue

        relation = _pinyin_relation(src, dst)

        if relation is not None:
            # Word boundaries are ambiguous (汪曉明主持 vs 黎拉打網球), so
            # offer both the expanded span (preselected - names are the
            # common case) and the raw span, and let the user pick.
            exp_src, exp_dst = _expand_span(original, corrected, a0, a1, b0, b1)
            if exp_dst in known_words:
                continue  # the correction is already covered by the dictionary
            candidates = [(exp_src, exp_dst, True)]
            if (exp_src, exp_dst) != (src, dst):
                candidates.append((src, dst, False))
            for c_src, c_dst, preselected in candidates:
                if not (2 <= len(c_dst) <= MAX_WORD_LEN) or c_dst in known_words:
                    continue
                key = ("word", c_src, c_dst)
                if key in seen:
                    continue
                seen.add(key)
                suggestions.append(
                    Suggestion(
                        kind="word",
                        src=c_src,
                        dst=c_dst,
                        fuzzy=relation == "fuzzy",
                        preselected=preselected,
                    )
                )
            continue

        if (src, dst) in known_rules:
            continue
        key = ("rule", src, dst)
        if key in seen:
            continue
        seen.add(key)
        suggestions.append(Suggestion(kind="rule", src=src, dst=dst))

    return suggestions


def apply_suggestions(
    suggestions: list[Suggestion], dictionary: UserDictionary
) -> None:
    """Add accepted suggestions to the dictionary (caller saves it)."""
    for s in suggestions:
        if s.kind == "word":
            dictionary.words.append(
                WordEntry(word=s.dst, enabled=True, use_prompt=True, fuzzy=s.fuzzy)
            )
        else:
            dictionary.replacements.append(
                ReplacementRule(src=s.src, dst=s.dst, enabled=True)
            )
