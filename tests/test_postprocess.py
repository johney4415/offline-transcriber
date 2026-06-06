import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from dictionary import ReplacementRule, UserDictionary, WordEntry
from postprocess import HomophoneCorrector, PostProcessor


def make_dict(words=None, replacements=None) -> UserDictionary:
    return UserDictionary(words=words or [], replacements=replacements or [])


class TestHomophoneCorrector:
    def test_basic_homophone_replacement(self):
        # 汪曉明 and 王小明 share pinyin wang-xiao-ming
        corrector = HomophoneCorrector([WordEntry(word="王小明")])
        assert corrector.correct("今天汪曉明來開會") == "今天王小明來開會"

    def test_already_correct_text_untouched(self):
        corrector = HomophoneCorrector([WordEntry(word="王小明")])
        assert corrector.correct("今天王小明來開會") == "今天王小明來開會"

    def test_no_match_untouched(self):
        corrector = HomophoneCorrector([WordEntry(word="王小明")])
        assert corrector.correct("今天李大華來開會") == "今天李大華來開會"

    def test_window_does_not_span_punctuation(self):
        corrector = HomophoneCorrector([WordEntry(word="王小明")])
        # wang / xiao+ming split by punctuation must NOT match
        text = "他姓汪，曉明天會到"
        assert corrector.correct(text) == text

    def test_heteronym_matching(self):
        # 銀行 háng: heteronym 行 (xíng/háng) must still match 銀航
        corrector = HomophoneCorrector([WordEntry(word="銀行")])
        assert corrector.correct("去銀航辦事") == "去銀行辦事"

    def test_fuzzy_disabled_by_default(self):
        # 李娜 (li-na) vs 黎拉 (li-la): l/n fuzzy off -> no replacement
        corrector = HomophoneCorrector([WordEntry(word="李娜", fuzzy=False)])
        assert corrector.correct("黎拉打網球") == "黎拉打網球"

    def test_fuzzy_enabled_l_n(self):
        corrector = HomophoneCorrector([WordEntry(word="李娜", fuzzy=True)])
        assert corrector.correct("黎拉打網球") == "李娜打網球"

    def test_fuzzy_zh_z(self):
        # 志強 zhi-qiang vs 自強 zi-qiang under zh/z fuzzy
        corrector = HomophoneCorrector([WordEntry(word="志強", fuzzy=True)])
        assert corrector.correct("自強來了") == "志強來了"

    def test_longest_word_wins(self):
        corrector = HomophoneCorrector(
            [WordEntry(word="王小"), WordEntry(word="王小明")]
        )
        assert corrector.correct("汪曉明來了") == "王小明來了"

    def test_disabled_entry_ignored(self):
        corrector = HomophoneCorrector([WordEntry(word="王小明", enabled=False)])
        assert corrector.correct("汪曉明來了") == "汪曉明來了"

    def test_single_char_words_ignored(self):
        # Single-char entries would over-match; they are skipped by design.
        corrector = HomophoneCorrector([WordEntry(word="明")])
        assert corrector.correct("民眾") == "民眾"

    def test_non_overlapping_replacements(self):
        corrector = HomophoneCorrector([WordEntry(word="王小明")])
        assert corrector.correct("汪曉明和汪曉明") == "王小明和王小明"


class TestPostProcessor:
    def test_simplified_to_taiwan_traditional(self):
        pp = PostProcessor(make_dict())
        assert pp.process("软件开发") == "軟體開發"

    def test_literal_replacement_runs_last(self):
        pp = PostProcessor(
            make_dict(replacements=[ReplacementRule(src="開會", dst="會議")])
        )
        assert pp.process("今天開會") == "今天會議"

    def test_full_pipeline(self):
        # Simplified input -> traditional -> homophone fix -> literal rule
        pp = PostProcessor(
            make_dict(
                words=[WordEntry(word="王小明")],
                replacements=[ReplacementRule(src="先生", dst="老師")],
            )
        )
        assert pp.process("汪晓明先生来了") == "王小明老師來了"

    def test_disabled_rule_ignored(self):
        pp = PostProcessor(
            make_dict(
                replacements=[ReplacementRule(src="開會", dst="會議", enabled=False)]
            )
        )
        assert pp.process("今天開會") == "今天開會"


class TestDictionaryPersistence:
    def test_roundtrip(self, tmp_path):
        d = make_dict(
            words=[WordEntry(word="王小明", fuzzy=True)],
            replacements=[ReplacementRule(src="a", dst="b")],
        )
        p = tmp_path / "dictionary.json"
        d.save(p)
        loaded = UserDictionary.load(p)
        assert loaded.words[0].word == "王小明"
        assert loaded.words[0].fuzzy is True
        assert loaded.replacements[0].src == "a"
        assert loaded.replacements[0].dst == "b"

    def test_load_missing_file(self, tmp_path):
        d = UserDictionary.load(tmp_path / "nope.json")
        assert d.words == [] and d.replacements == []


class TestInitialPrompt:
    @staticmethod
    def char_count_tokens(text: str) -> int:
        # Stand-in tokenizer: 1 char = 1 token (real one provided by model)
        return len(text)

    def test_basic_prompt(self):
        d = make_dict(words=[WordEntry(word="王小明")])
        prompt = d.build_initial_prompt(self.char_count_tokens)
        assert "王小明" in prompt
        assert prompt.startswith("以下是繁體中文的逐字稿。")

    def test_no_words(self):
        d = make_dict()
        assert d.build_initial_prompt(self.char_count_tokens) == "以下是繁體中文的逐字稿。"

    def test_truncation_keeps_trailing_words(self):
        words = [WordEntry(word=f"詞彙{i:04d}") for i in range(100)]
        d = make_dict(words=words)
        prompt = d.build_initial_prompt(self.char_count_tokens, max_tokens=50)
        assert self.char_count_tokens(prompt) <= 50
        # Trailing words survive (they outlive Whisper's keep-last truncation)
        assert "詞彙0099" in prompt
        assert "詞彙0000" not in prompt

    def test_use_prompt_false_excluded(self):
        d = make_dict(
            words=[
                WordEntry(word="王小明", use_prompt=False),
                WordEntry(word="李大華"),
            ]
        )
        prompt = d.build_initial_prompt(self.char_count_tokens)
        assert "王小明" not in prompt
        assert "李大華" in prompt


class TestSrtFormat:
    def test_format(self):
        from transcriber import Segment, format_srt

        srt = format_srt(
            [Segment(start=0.0, end=2.5, text="你好"), Segment(start=2.5, end=5.0, text="世界")]
        )
        assert "1\n00:00:00,000 --> 00:00:02,500\n你好" in srt
        assert "2\n00:00:02,500 --> 00:00:05,000\n世界" in srt
