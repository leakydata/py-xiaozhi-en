"""Regression tests for mixing TTS and music from separate queues.

Covers PcmFifo's sample-level behaviour, and _pull_mixed's mixing, ducking and clipping.
Background: TTS and music once shared one FIFO, so sentence-by-sentence TTS interleaved the frames and you heard both at once, stuttering.
"""

import numpy as np
import pytest

from src.utils.config_manager import initialize_config

try:
    initialize_config()
except Exception:
    pass

from src.audio_codecs.audio_buffer import PcmFifo  # noqa: E402
from src.audio_codecs.audio_codec import (  # noqa: E402
    _MUSIC_DUCK_GAIN,
    AudioCodec,
)


class TestPcmFifo:
    def test_pull_basic(self):
        f = PcmFifo(1000)
        f.push(np.ones(300, dtype=np.float32))
        out = f.pull(200)
        assert out.shape == (200,)
        assert np.all(out == 1)
        assert f.size == 100

    def test_pull_pads_zeros_when_short(self):
        f = PcmFifo(1000)
        f.push(np.ones(100, dtype=np.float32))
        out = f.pull(200)
        assert np.all(out[:100] == 1)
        assert np.all(out[100:] == 0)
        assert f.size == 0

    def test_pull_empty_returns_none(self):
        f = PcmFifo(1000)
        assert f.pull(10) is None

    def test_push_drops_oldest_over_capacity(self):
        f = PcmFifo(1000)
        f.push(np.zeros(600, dtype=np.float32))
        f.push(np.ones(600, dtype=np.float32))
        assert f.size == 1000
        assert f.dropped == 200
        out = f.pull(1000)
        # the oldest 200 zeros are dropped, leaving 400 zeros and 600 ones
        assert np.all(out[:400] == 0)
        assert np.all(out[400:] == 1)

    def test_clear(self):
        f = PcmFifo(1000)
        f.push(np.ones(500, dtype=np.float32))
        assert f.clear() == 500
        assert f.size == 0
        assert f.pull(10) is None

    def test_multichannel_flattened(self):
        f = PcmFifo(1000)
        f.push(np.ones((100, 2), dtype=np.float32))
        assert f.size == 200


class TestMixing:
    @pytest.fixture()
    def codec(self):
        return AudioCodec()

    def test_music_only_full_gain(self, codec):
        n = codec._mix_chunk
        codec._music_fifo.push(np.full(n, 0.4, dtype=np.float32))
        out = codec._pull_mixed(n)
        assert np.allclose(out, 0.4)

    def test_tts_only(self, codec):
        n = codec._mix_chunk
        codec._tts_fifo.push(np.full(n, 0.5, dtype=np.float32))
        out = codec._pull_mixed(n)
        assert np.allclose(out, 0.5)

    def test_tts_and_music_mixed_with_duck(self, codec):
        n = codec._mix_chunk
        codec._tts_fifo.push(np.full(n, 0.5, dtype=np.float32))
        codec._music_fifo.push(np.full(n, 0.4, dtype=np.float32))
        out = codec._pull_mixed(n)
        assert np.allclose(out, 0.5 + _MUSIC_DUCK_GAIN * 0.4)

    def test_duck_hangover_then_recover(self, codec):
        n = codec._mix_chunk
        # after a burst of TTS the music stays ducked through the hangover
        codec._tts_fifo.push(np.full(n, 0.5, dtype=np.float32))
        codec._music_fifo.push(np.full(n, 0.4, dtype=np.float32))
        codec._pull_mixed(n)

        codec._music_fifo.push(np.full(n, 0.4, dtype=np.float32))
        out = codec._pull_mixed(n)
        assert np.allclose(out, _MUSIC_DUCK_GAIN * 0.4)

        # once the hangover expires it returns to full volume
        for _ in range(15):
            codec._music_fifo.push(np.full(n, 0.4, dtype=np.float32))
            out = codec._pull_mixed(n)
        assert np.allclose(out, 0.4)

    def test_clip_protection(self, codec):
        n = codec._mix_chunk
        codec._tts_fifo.push(np.full(n, 0.9, dtype=np.float32))
        codec._music_fifo.push(np.full(n, 0.9, dtype=np.float32))
        out = codec._pull_mixed(n)
        assert out.max() <= 1.0

    def test_both_empty_returns_none(self, codec):
        assert codec._pull_mixed(codec._mix_chunk) is None

    def test_clear_semantics_are_independent(self, codec):
        n = codec._mix_chunk
        codec._tts_fifo.push(np.full(n, 0.5, dtype=np.float32))
        codec._music_fifo.push(np.full(n, 0.4, dtype=np.float32))
        codec._tts_fifo.clear()
        # clearing TTS leaves the music alone
        assert codec._music_fifo.size == n
