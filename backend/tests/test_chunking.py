import pytest

from app.ingest.chunking import MAX_CHARS, OVERLAP_CHARS, TARGET_CHARS, chunk_text

PARA = " ".join(["kata"] * 120)  # ~599 karakter


def long_text(paragraphs: int = 12) -> str:
    return "\n\n".join(f"Paragraf {i}. " + " ".join(f"kalimat{j} berisi kata." for j in range(40)) for i in range(paragraphs))


def test_empty_and_whitespace_only_give_no_chunks():
    assert chunk_text("") == []
    assert chunk_text("  \n\t ") == []


def test_short_text_is_a_single_chunk_with_correct_offsets():
    text = "  Halo dunia.  "
    [chunk] = chunk_text(text)
    assert chunk.text == "Halo dunia."
    assert text[chunk.char_start : chunk.char_end] == chunk.text
    assert chunk.index == 0


def test_offsets_always_match_source_text():
    text = long_text()
    chunks = chunk_text(text)
    assert len(chunks) > 3
    for chunk in chunks:
        assert text[chunk.char_start : chunk.char_end] == chunk.text


def test_chunk_sizes_respect_limits():
    chunks = chunk_text(long_text())
    assert all(len(c.text) <= MAX_CHARS for c in chunks)
    # Semua chunk kecuali yang terakhir sudah mencapai target.
    assert all(len(c.text) >= TARGET_CHARS for c in chunks[:-1])


def test_consecutive_chunks_overlap_by_about_the_configured_amount():
    chunks = chunk_text(long_text())
    for prev, nxt in zip(chunks, chunks[1:]):
        overlap = prev.char_end - nxt.char_start
        assert 0 < overlap <= OVERLAP_CHARS + 60  # bisa bergeser sedikit ke awal kata


def test_indexes_are_sequential():
    assert [c.index for c in chunk_text(long_text())] == list(range(len(chunk_text(long_text()))))


def test_every_non_space_character_is_covered():
    text = long_text()
    covered = [False] * len(text)
    for chunk in chunk_text(text):
        for i in range(chunk.char_start, chunk.char_end):
            covered[i] = True
    missing = [i for i, ch in enumerate(text) if not ch.isspace() and not covered[i]]
    assert missing == []


def test_prefers_cutting_at_paragraph_boundary():
    text = "\n\n".join([PARA] * 5)
    first = chunk_text(text)[0]
    assert first.text == PARA + "\n\n" + PARA


def test_chunks_do_not_start_mid_word():
    text = long_text()
    for chunk in chunk_text(text)[1:]:
        assert text[chunk.char_start - 1].isspace()


def test_text_without_any_whitespace_is_hard_cut_and_terminates():
    text = "x" * 4000
    chunks = chunk_text(text)
    assert all(len(c.text) <= MAX_CHARS for c in chunks)
    assert chunks[-1].char_end == len(text)
    for chunk in chunks:
        assert text[chunk.char_start : chunk.char_end] == chunk.text


def test_token_estimate_is_positive_and_scales_with_length():
    small, large = chunk_text("halo"), chunk_text(long_text())
    assert small[0].token_estimate >= 1
    assert large[0].token_estimate > small[0].token_estimate


@pytest.mark.parametrize("target,max_chars,overlap", [(500, 400, 100), (500, 600, 500), (500, 600, -1)])
def test_invalid_parameters_are_rejected(target, max_chars, overlap):
    with pytest.raises(ValueError):
        chunk_text("abc", target=target, max_chars=max_chars, overlap=overlap)
