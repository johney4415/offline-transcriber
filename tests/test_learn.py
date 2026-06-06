import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from dictionary import ReplacementRule, UserDictionary, WordEntry
from learn import apply_suggestions, extract_suggestions


def empty_dict() -> UserDictionary:
    return UserDictionary()


class TestExtractSuggestions:
    def test_homophone_correction_suggests_word(self):
        original = "今天的會議由汪曉明主持"
        corrected = "今天的會議由王小明主持"
        suggestions = extract_suggestions(original, corrected, empty_dict())
        # Expanded variant 王小明 is preselected; raw variant 王小 is offered
        # unchecked because word boundaries are ambiguous.
        by_dst = {s.dst: s for s in suggestions}
        assert by_dst["王小明"].kind == "word"
        assert by_dst["王小明"].preselected is True
        assert by_dst["王小明"].fuzzy is False
        assert by_dst["王小"].preselected is False

    def test_middle_char_correction_expands_both_sides(self):
        # Only the middle char differs: 王曉明 -> 王小明
        original = "請王曉明發言"
        corrected = "請王小明發言"
        suggestions = extract_suggestions(original, corrected, empty_dict())
        assert any(s.dst == "王小明" and s.preselected for s in suggestions)

    def test_fuzzy_homophone_flagged(self):
        # 黎拉 li-la vs 李娜 li-na: only matches under l/n fuzzy
        original = "黎拉打網球"
        corrected = "李娜打網球"
        suggestions = extract_suggestions(original, corrected, empty_dict())
        by_dst = {s.dst: s for s in suggestions}
        assert by_dst["李娜"].kind == "word"
        assert by_dst["李娜"].fuzzy is True

    def test_non_homophone_suggests_rule(self):
        # 計畫 ji-hua vs 企劃 qi-hua: different pinyin -> literal rule
        original = "下一季的計畫內容"
        corrected = "下一季的企劃內容"
        suggestions = extract_suggestions(original, corrected, empty_dict())
        assert len(suggestions) == 1
        s = suggestions[0]
        assert s.kind == "rule"
        assert s.src == "計畫"
        assert s.dst == "企劃"

    def test_pure_deletion_ignored(self):
        # Removing filler words is rephrasing, not a term fix
        original = "嗯今天我們開會"
        corrected = "今天我們開會"
        assert extract_suggestions(original, corrected, empty_dict()) == []

    def test_identical_text_no_suggestions(self):
        text = "完全一樣的內容"
        assert extract_suggestions(text, text, empty_dict()) == []

    def test_long_rewrite_ignored(self):
        original = "這段話完全不行需要整個重新寫過才可以"
        corrected = "重寫後內容截然不同的一段話表達同樣意思"
        assert extract_suggestions(original, corrected, empty_dict()) == []

    def test_known_word_not_resuggested(self):
        d = UserDictionary(words=[WordEntry(word="王小明")])
        suggestions = extract_suggestions("汪曉明來了", "王小明來了", d)
        assert suggestions == []

    def test_known_rule_not_resuggested(self):
        d = UserDictionary(replacements=[ReplacementRule(src="計畫", dst="企劃")])
        suggestions = extract_suggestions("這個計畫不錯", "這個企劃不錯", d)
        assert suggestions == []

    def test_duplicate_corrections_deduped(self):
        original = "汪曉明說，請找汪曉明"
        corrected = "王小明說，請找王小明"
        suggestions = extract_suggestions(original, corrected, empty_dict())
        # The same correction appearing twice yields one suggestion per variant
        assert sum(1 for s in suggestions if s.dst == "王小明") == 1

    def test_multiple_different_corrections(self):
        original = "汪曉明負責這個計畫"
        corrected = "王小明負責這個企劃"
        suggestions = extract_suggestions(original, corrected, empty_dict())
        kinds = {(s.kind, s.dst) for s in suggestions}
        assert ("word", "王小明") in kinds
        assert ("rule", "企劃") in kinds


class TestApplySuggestions:
    def test_apply_word_and_rule(self):
        d = empty_dict()
        suggestions = extract_suggestions(
            "汪曉明負責這個計畫", "王小明負責這個企劃", d
        )
        apply_suggestions(suggestions, d)
        assert any(w.word == "王小明" for w in d.words)
        assert any(r.src == "計畫" and r.dst == "企劃" for r in d.replacements)

    def test_applied_word_takes_effect_in_pipeline(self):
        from postprocess import PostProcessor

        d = empty_dict()
        apply_suggestions(
            extract_suggestions("汪曉明來了", "王小明來了", d), d
        )
        pp = PostProcessor(d)
        # A different homophone spelling is now corrected too
        assert pp.process("王曉明來了") == "王小明來了"
