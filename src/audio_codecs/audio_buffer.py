"""A sample-level PCM buffer.

The thread-safe FIFO the output callback mixes from
"""

import threading
from collections import deque

import numpy as np


class PcmFifo:
    """A sample-level PCM FIFO (float32 mono, thread-safe).

    Written from the asyncio thread and read from the audio output callback thread;
    this is what lets TTS and music stay separate and be mixed in the output callback.

    - push: past capacity the oldest samples go, and are counted in dropped
    - pull: returns a fixed-size block, zero-padded if short; None when there is nothing at all
    """

    def __init__(self, max_samples: int):
        self._chunks: deque = deque()
        self._offset = 0  # how many samples of the first block have been consumed
        self._size = 0  # how many samples are readable in total
        self._max = int(max_samples)
        self._lock = threading.Lock()
        self.dropped = 0

    @property
    def size(self) -> int:
        return self._size

    def push(self, pcm: np.ndarray) -> None:
        """Append float32 mono data, dropping the oldest once capacity is exceeded."""
        if pcm.ndim > 1:
            pcm = pcm.reshape(-1)
        if pcm.dtype != np.float32:
            pcm = pcm.astype(np.float32)
        with self._lock:
            self._chunks.append(pcm)
            self._size += len(pcm)
            while self._size > self._max and self._chunks:
                head = self._chunks[0]
                remain = len(head) - self._offset
                drop = min(remain, self._size - self._max)
                self._offset += drop
                self._size -= drop
                self.dropped += drop
                if self._offset >= len(head):
                    self._chunks.popleft()
                    self._offset = 0

    def pull(self, n: int) -> np.ndarray | None:
        """Take n samples; None when empty, zero-padded when short."""
        with self._lock:
            if self._size == 0:
                return None
            out = np.zeros(n, dtype=np.float32)
            filled = 0
            while filled < n and self._chunks:
                head = self._chunks[0]
                avail = len(head) - self._offset
                take = min(avail, n - filled)
                out[filled : filled + take] = head[self._offset : self._offset + take]
                filled += take
                self._offset += take
                self._size -= take
                if self._offset >= len(head):
                    self._chunks.popleft()
                    self._offset = 0
            return out

    def clear(self) -> int:
        """Empty it, returning how many samples were discarded."""
        with self._lock:
            count = self._size
            self._chunks.clear()
            self._offset = 0
            self._size = 0
            return count
