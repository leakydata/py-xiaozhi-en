"""Keep the kernel's real-time watchdog from killing the app.

The app was dying mid-reply with SIGKILL - caught by gdb on the third time -
and nothing anywhere said who sent it. The kernel did, and by default says
nothing about it: a thread scheduled real-time that runs 200 ms of CPU without
blocking is killed outright, along with its whole process, when its
RLIMIT_RTTIME hard limit is reached.

That limit is set the moment audio opens. PipeWire's ALSA plugin asks rtkit to
make each stream's `data-loop.0` thread real-time (RR, priority 20), and rtkit
only grants it under RLIMIT_RTTIME of 200 ms, soft and hard alike - so the
first breach is a SIGKILL, not a warning. Those threads are PipeWire's, inside
this process; no Python runs on them. Measured on this machine:

    after opening audio:  Max realtime timeout  200000  200000  us
    data-loop.0  RR 20    (one per stream)

The watchdog only applies to real-time threads. Moving these two back to the
normal scheduler takes them out of its reach, and costs nothing that matters
here: they do a few microseconds of copying per 20 ms period on a machine that
is mostly idle. rtkit promotes them asynchronously after a stream starts, and
streams are reopened on device changes, so this is checked periodically
rather than once.
"""

from __future__ import annotations

import os
import sys

from src.logging import get_logger

logger = get_logger()

#: Thread names PipeWire gives its real-time audio loops inside a client.
_PIPEWIRE_RT_THREADS = ("data-loop",)
_RESET_ON_FORK = getattr(os, "SCHED_RESET_ON_FORK", 0x40000000)


def _realtime_policies() -> tuple:
    return tuple(
        p
        for p in (getattr(os, "SCHED_FIFO", None), getattr(os, "SCHED_RR", None))
        if p is not None
    )


def demote_realtime_audio_threads(task_dir: str = "/proc/self/task") -> list[str]:
    """Move this process's PipeWire real-time threads to the normal scheduler.

    Returns "name[tid]" for each one moved. Lowering a thread's own priority
    needs no privilege, so this works as the user.
    """
    if not sys.platform.startswith("linux") or not hasattr(os, "sched_setscheduler"):
        return []
    realtime = _realtime_policies()
    moved: list[str] = []
    try:
        tids = os.listdir(task_dir)
    except OSError:
        return []
    for tid in tids:
        try:
            with open(os.path.join(task_dir, tid, "comm")) as f:
                name = f.read().strip()
        except OSError:
            continue  # the thread finished while we looked
        if not name.startswith(_PIPEWIRE_RT_THREADS):
            continue
        try:
            # rtkit sets SCHED_RESET_ON_FORK alongside the policy, so the raw
            # value is RR | 0x40000000 and has to be masked to be recognised.
            policy = os.sched_getscheduler(int(tid)) & ~_RESET_ON_FORK
            if policy not in realtime:
                continue
            # And the flag has to be kept: the kernel lets an unprivileged
            # thread leave real-time scheduling, but not drop reset-on-fork,
            # and refuses the whole change (EPERM) if asked to.
            os.sched_setscheduler(
                int(tid), os.SCHED_OTHER | _RESET_ON_FORK, os.sched_param(0)
            )
            moved.append(f"{name}[{tid}]")
        except (OSError, ValueError) as e:
            logger.warning(f"could not take {name}[{tid}] off real-time: {e}")
    return moved


def realtime_timeout_us() -> int | None:
    """This process's RLIMIT_RTTIME hard limit, for the log."""
    try:
        import resource

        hard = resource.getrlimit(resource.RLIMIT_RTTIME)[1]
        return None if hard == resource.RLIM_INFINITY else int(hard)
    except Exception:
        return None
