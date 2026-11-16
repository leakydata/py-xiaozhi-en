"""PortAudio is never torn down while a settings test has a stream open."""

import threading
import time

from src.utils import audio_utils


def test_reinitialising_waits_for_an_open_test_stream(monkeypatch):
    order = []
    monkeypatch.setattr(audio_utils, "_reinitialize", lambda: order.append("reinit"))
    monkeypatch.setattr(audio_utils.sd, "query_devices", lambda: [])

    def test_stream():
        with audio_utils.PORTAUDIO_LOCK:
            order.append("test start")
            time.sleep(0.3)
            order.append("test end")

    t = threading.Thread(target=test_stream)
    t.start()
    time.sleep(0.05)
    audio_utils.refresh_portaudio_devices(reinitialize=True)
    t.join()
    assert order == ["test start", "test end", "reinit"]


def test_a_test_that_never_ends_only_skips_the_reinitialisation(monkeypatch):
    calls = []
    monkeypatch.setattr(audio_utils, "_reinitialize", lambda: calls.append("reinit"))
    monkeypatch.setattr(audio_utils.sd, "query_devices", lambda: [{"name": "x"}])
    monkeypatch.setattr(audio_utils, "_REINIT_WAIT_S", 0.1)
    held = threading.Event()
    release = threading.Event()

    def stuck():
        with audio_utils.PORTAUDIO_LOCK:
            held.set()
            release.wait(2)

    t = threading.Thread(target=stuck)
    t.start()
    held.wait(1)
    assert audio_utils.refresh_portaudio_devices(reinitialize=True) == [{"name": "x"}]
    release.set()
    t.join()
    assert calls == []


def test_without_a_test_running_it_reinitialises(monkeypatch):
    calls = []
    monkeypatch.setattr(audio_utils, "_reinitialize", lambda: calls.append("reinit"))
    monkeypatch.setattr(audio_utils.sd, "query_devices", lambda: [])
    audio_utils.refresh_portaudio_devices(reinitialize=True)
    audio_utils.refresh_portaudio_devices(reinitialize=False)
    assert calls == ["reinit"]
