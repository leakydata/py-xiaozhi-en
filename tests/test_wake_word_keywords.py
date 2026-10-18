"""The wake word the app listens for is the one in the config."""

from src.audio_processing import wake_word_detect
from src.audio_processing.keyword_converters import convert_wake_word
from src.audio_processing.wake_word_detect import WakeWordDetector


class _Config:
    def __init__(self, word):
        self.word = word

    def get_config(self, key, default=None):
        if key == "WAKE_WORD_OPTIONS.WAKE_WORD":
            return self.word
        if key == "WAKE_WORD_OPTIONS.WAKE_WORD_LANG":
            return "en"
        return default


def test_a_two_word_label_has_no_space_in_it():
    """sherpa reads everything after the first token run as vocabulary, so a
    space inside the @label made the whole keywords file unloadable."""
    line, lang, _ = convert_wake_word("hey computer")
    tokens, label = line.split(" @")
    assert lang == "en"
    assert " " not in label
    assert label == "HEY_COMPUTER"
    assert tokens.startswith("▁HE")


def test_a_stale_keywords_file_is_rewritten_from_the_config(tmp_path, monkeypatch):
    monkeypatch.setattr(wake_word_detect, "get_config", lambda: _Config("hey computer"))
    path = tmp_path / "en_keywords.txt"
    path.write_text("▁MO S S @MOSS\n", encoding="utf-8")
    WakeWordDetector._sync_keywords_file(path, "en")
    assert path.read_text(encoding="utf-8").strip().endswith("@HEY_COMPUTER")


def test_a_missing_keywords_file_is_created(tmp_path, monkeypatch):
    monkeypatch.setattr(wake_word_detect, "get_config", lambda: _Config("hey computer"))
    path = tmp_path / "keywords" / "en_keywords.txt"
    WakeWordDetector._sync_keywords_file(path, "en")
    assert path.exists()


def test_a_file_that_already_matches_is_left_alone(tmp_path, monkeypatch):
    monkeypatch.setattr(wake_word_detect, "get_config", lambda: _Config("hey computer"))
    path = tmp_path / "en_keywords.txt"
    line, _, _ = convert_wake_word("hey computer")
    path.write_text(line + "\n", encoding="utf-8")
    before = path.stat().st_mtime_ns
    WakeWordDetector._sync_keywords_file(path, "en")
    assert path.stat().st_mtime_ns == before


def test_a_wake_word_in_the_other_language_does_not_clobber_the_file(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(wake_word_detect, "get_config", lambda: _Config("你好小智"))
    path = tmp_path / "en_keywords.txt"
    path.write_text("▁MO S S @MOSS\n", encoding="utf-8")
    WakeWordDetector._sync_keywords_file(path, "en")
    assert path.read_text(encoding="utf-8") == "▁MO S S @MOSS\n"


def test_no_configured_word_changes_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(wake_word_detect, "get_config", lambda: _Config(""))
    path = tmp_path / "en_keywords.txt"
    path.write_text("▁MO S S @MOSS\n", encoding="utf-8")
    WakeWordDetector._sync_keywords_file(path, "en")
    assert path.read_text(encoding="utf-8") == "▁MO S S @MOSS\n"


def test_the_detector_loads_a_model_with_the_synced_keywords(tmp_path, monkeypatch):
    """The whole path, not just the sync: the stale file came right back as an
    unloadable one because a decorator moved with an insertion."""
    from pathlib import Path

    monkeypatch.setattr(wake_word_detect, "get_config", lambda: _Config("hey computer"))
    detector = WakeWordDetector()
    detector._model_dir = Path(__file__).resolve().parent.parent / "models" / "en"
    monkeypatch.setattr(
        wake_word_detect,
        "get_user_keywords_path",
        lambda lang: tmp_path / f"{lang}_keywords.txt",
    )
    (tmp_path / "en_keywords.txt").write_text("▁MO S S @MOSS\n", encoding="utf-8")
    assert detector._load_model()
    assert (tmp_path / "en_keywords.txt").read_text().strip().endswith("@HEY_COMPUTER")
