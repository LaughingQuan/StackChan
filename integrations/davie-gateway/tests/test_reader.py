from __future__ import annotations

from stackchan_davie_gateway.reader import ReaderLibrary, reader_segments


def test_reader_segments_strips_html_and_keeps_sentences_bounded() -> None:
    segments = reader_segments("<h1>Chapter One</h1><p>Hello world. This is a test.</p>", max_chars=24)
    assert segments
    assert all("<" not in item for item in segments)
    assert all(len(item) <= 24 for item in segments)
    assert " ".join(segments).startswith("Chapter One")


def test_reader_progress_persists_and_playing_restores_as_paused(tmp_path) -> None:
    path = tmp_path / "readers.json"
    library = ReaderLibrary(path)
    reader = library.for_device("stackchan-1")
    reader.load("A short book", "First sentence. Second sentence. Third sentence.")
    assert reader.resume() is True
    reader.advance()

    restored = ReaderLibrary(path).for_device("stackchan-1")
    assert restored.title == "A short book"
    assert restored.index == 1
    assert restored.state == "paused"
    assert restored.current() == "Second sentence."


def test_reader_pause_and_resume_repeat_interrupted_segment() -> None:
    reader = ReaderLibrary().for_device("stackchan-1")
    reader.load("Test", "First sentence. Second sentence.")
    reader.resume()
    assert reader.current() == "First sentence."
    reader.pause()
    reader.resume()
    assert reader.current() == "First sentence."
    reader.advance()
    assert reader.current() == "Second sentence."


def test_reader_can_be_cleared_and_removed_from_persistent_library(tmp_path) -> None:
    path = tmp_path / "readers.json"
    library = ReaderLibrary(path)
    reader = library.for_device("stackchan-1")
    reader.load("Test", "First sentence. Second sentence.")

    assert reader.clear() is True
    assert reader.status()["state"] == "idle"
    assert reader.status()["segment_count"] == 0
    assert library.remove("stackchan-1") is True
    assert "stackchan-1" not in path.read_text(encoding="utf-8")
