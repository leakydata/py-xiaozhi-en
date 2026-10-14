"""PipeWire's real-time audio threads are moved off real-time scheduling.

The kernel SIGKILLs a process whose real-time thread runs 200 ms without
blocking (RLIMIT_RTTIME, which rtkit sets to 200 ms soft and hard). That was
the app's silent mid-reply death. These pin the two details that made the
first attempt silently do nothing.
"""

import os

import pytest

from src.audio_codecs import realtime_guard as rg

RESET = rg._RESET_ON_FORK


@pytest.fixture
def tasks(tmp_path):
    def make(threads):
        for tid, name in threads.items():
            (tmp_path / str(tid)).mkdir()
            (tmp_path / str(tid) / "comm").write_text(name + "\n")
        return str(tmp_path)

    return make


def test_rtkit_flag_is_masked_and_kept(tasks, monkeypatch):
    task_dir = tasks({101: "data-loop.0", 102: "python", 103: "data-loop.0"})
    policies = {
        101: os.SCHED_RR | RESET,
        102: os.SCHED_OTHER,
        103: os.SCHED_FIFO | RESET,
    }
    calls = []
    monkeypatch.setattr(os, "sched_getscheduler", lambda tid: policies[tid])
    monkeypatch.setattr(
        os, "sched_setscheduler", lambda tid, pol, param: calls.append((tid, pol))
    )

    moved = rg.demote_realtime_audio_threads(task_dir)

    # Both PipeWire threads recognised despite the flag, the python thread left alone.
    assert moved == ["data-loop.0[101]", "data-loop.0[103]"] or sorted(moved) == [
        "data-loop.0[101]",
        "data-loop.0[103]",
    ]
    # And moved to normal scheduling with reset-on-fork kept, which is the only
    # way the kernel allows it without privilege.
    assert sorted(calls) == [
        (101, os.SCHED_OTHER | RESET),
        (103, os.SCHED_OTHER | RESET),
    ]


def test_already_normal_threads_are_left_alone(tasks, monkeypatch):
    task_dir = tasks({201: "data-loop.0"})
    monkeypatch.setattr(os, "sched_getscheduler", lambda tid: os.SCHED_OTHER | RESET)
    monkeypatch.setattr(
        os, "sched_setscheduler", lambda *a: pytest.fail("should not move")
    )
    assert rg.demote_realtime_audio_threads(task_dir) == []


def test_a_refusal_is_reported_not_raised(tasks, monkeypatch):
    task_dir = tasks({301: "data-loop.0"})
    monkeypatch.setattr(os, "sched_getscheduler", lambda tid: os.SCHED_RR)

    def refuse(*a):
        raise PermissionError(1, "Operation not permitted")

    monkeypatch.setattr(os, "sched_setscheduler", refuse)
    assert rg.demote_realtime_audio_threads(task_dir) == []


def test_threads_that_vanish_mid_scan_are_skipped(tmp_path):
    (tmp_path / "401").mkdir()  # no comm file: the thread exited
    assert rg.demote_realtime_audio_threads(str(tmp_path)) == []
