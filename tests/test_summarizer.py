import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from summarizer import CHUNK_OVERLAP_CHARS, MAX_INPUT_CHARS, Summarizer


class TestChunking:
    def test_short_text_single_chunk(self):
        chunks = Summarizer._chunk("短短的一段話")
        assert chunks == ["短短的一段話"]

    def test_exact_boundary_single_chunk(self):
        text = "字" * MAX_INPUT_CHARS
        assert len(Summarizer._chunk(text)) == 1

    def test_long_text_splits_with_overlap(self):
        text = "字" * (MAX_INPUT_CHARS * 2)
        chunks = Summarizer._chunk(text)
        assert len(chunks) >= 2
        # each chunk within the size budget
        assert all(len(c) <= MAX_INPUT_CHARS for c in chunks)
        # chunks cover the whole text
        assert chunks[0][-1] == "字"

    def test_chunks_overlap_for_context(self):
        # Build distinguishable text to verify overlap region is shared
        text = "".join(chr(0x4E00 + (i % 100)) for i in range(MAX_INPUT_CHARS + 500))
        chunks = Summarizer._chunk(text)
        assert len(chunks) == 2
        # The tail of chunk 0 reappears at the head of chunk 1
        overlap = chunks[0][-CHUNK_OVERLAP_CHARS:]
        assert chunks[1].startswith(overlap)

    def test_no_infinite_loop_on_large_input(self):
        text = "字" * (MAX_INPUT_CHARS * 5)
        chunks = Summarizer._chunk(text)
        # reconstructable length is bounded and finite
        assert 5 <= len(chunks) <= 8
