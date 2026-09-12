"""Log handlers.

Provides:
- a file handler that rotates on both time and size
- an asynchronous handler
"""

import atexit
import gzip
import logging
import queue
import shutil
import time
from logging.handlers import BaseRotatingHandler, QueueHandler, QueueListener
from pathlib import Path
from typing import Union


class TimeSizeRotatingFileHandler(BaseRotatingHandler):
    """A file handler that rotates two ways.

    It rotates on time and on size; whichever comes first triggers it.
    """

    def __init__(
        self,
        filename: Union[str, Path],
        when: str = "midnight",
        interval: int = 1,
        max_bytes: int = 10 * 1024 * 1024,  # 10MB
        backup_count: int = 30,
        encoding: str = "utf-8",
        delay: bool = False,
        compress: bool = False,
    ) -> None:
        self.baseFilename = str(filename)
        self.when = when.upper()
        self.interval = interval
        self.max_bytes = max_bytes
        self.backup_count = backup_count
        self.compress = compress

        # work out the time rollover
        self._compute_rollover_time()

        # initialise the base class
        super().__init__(self.baseFilename, "a", encoding=encoding, delay=delay)

    def _compute_rollover_time(self) -> None:
        """
        Work out when the next rollover is due.
        """
        current_time = int(time.time())

        if self.when == "MIDNIGHT":
            # seconds until midnight
            t = time.localtime(current_time)
            current_hour = t.tm_hour
            current_minute = t.tm_min
            current_second = t.tm_sec
            seconds_to_midnight = (
                (24 - current_hour - 1) * 3600
                + (60 - current_minute - 1) * 60
                + (60 - current_second)
            )
            self.rollover_at = current_time + seconds_to_midnight
            self.suffix = "%Y-%m-%d"
        elif self.when == "H":
            self.rollover_at = current_time + 3600 * self.interval
            self.suffix = "%Y-%m-%d_%H"
        elif self.when == "D":
            self.rollover_at = current_time + 86400 * self.interval
            self.suffix = "%Y-%m-%d"
        else:
            self.rollover_at = current_time + 86400
            self.suffix = "%Y-%m-%d"

    def shouldRollover(self, record: logging.LogRecord) -> bool:
        """
        Whether a rollover is due.
        """
        # check the time
        if time.time() >= self.rollover_at:
            return True

        # check the size
        if self.max_bytes > 0:
            if self.stream is None:
                self.stream = self._open()
            try:
                self.stream.seek(0, 2)  # seek to the end of the file
                if self.stream.tell() + len(self.format(record)) >= self.max_bytes:
                    return True
            except (OSError, ValueError):
                pass

        return False

    def doRollover(self) -> None:
        """
        Do the rollover.
        """
        if self.stream:
            self.stream.close()
            self.stream = None

        # build the rotated file name
        current_time = time.time()
        time_suffix = time.strftime(self.suffix, time.localtime(current_time))

        # was this triggered by size? (it can happen more than once a day)
        base_path = Path(self.baseFilename)
        base_name = base_path.stem
        base_ext = base_path.suffix
        parent = base_path.parent

        # assemble the rotated file name
        rotated_name = f"{base_name}.{time_suffix}"

        # if that name is taken, add a counter
        counter = 0
        while True:
            if counter == 0:
                dfn = parent / f"{rotated_name}{base_ext}"
            else:
                dfn = parent / f"{rotated_name}.{counter}{base_ext}"

            if self.compress:
                dfn = Path(str(dfn) + ".gz")

            if not dfn.exists():
                break
            counter += 1

        # rotate
        source_path = Path(self.baseFilename)
        if source_path.exists():
            if self.compress:
                self._compress_file(source_path, dfn)
                source_path.unlink()
            else:
                shutil.move(str(source_path), str(dfn))

        # clean up the old files
        self._cleanup_old_files(parent, base_name)

        # work out the next rollover time
        self._compute_rollover_time()

        # reopen the file
        if not self.delay:
            self.stream = self._open()

    def _compress_file(self, source: Path, dest: Path) -> None:
        """
        Compress a file.
        """
        with open(source, "rb") as f_in:
            with gzip.open(dest, "wb") as f_out:
                shutil.copyfileobj(f_in, f_out)

    def _cleanup_old_files(self, directory: Path, base_name: str) -> None:
        """
        Delete the old files beyond the number kept.
        """
        if self.backup_count <= 0:
            return

        # find every rotated file
        pattern = f"{base_name}.*"
        log_files = []

        for f in directory.glob(pattern):
            if f.name != Path(self.baseFilename).name:
                log_files.append(f)

        # sort by modification time
        log_files.sort(key=lambda x: x.stat().st_mtime, reverse=True)

        # delete the ones past the limit
        for old_file in log_files[self.backup_count :]:
            try:
                old_file.unlink()
            except OSError:
                pass


class AsyncHandler(QueueHandler):
    """An asynchronous log handler.

    A queue moves the writing onto a background thread, so the main thread is not blocked.
    """

    def __init__(
        self,
        handlers: list[logging.Handler],
        queue_size: int = 10000,
        respect_handler_level: bool = True,
    ) -> None:
        # create the queue
        self._log_queue: queue.Queue = queue.Queue(maxsize=queue_size)
        super().__init__(self._log_queue)

        # create the listener
        self._listener = QueueListener(
            self._log_queue,
            *handlers,
            respect_handler_level=respect_handler_level,
        )
        self._listener.start()

        # register the cleanup for exit
        atexit.register(self.close)

    def close(self) -> None:
        """
        Close the handler.
        """
        try:
            self._listener.stop()
        except Exception as e:
            logging.getLogger(__name__).debug(f"failed to stop the log listener: {e}")
        super().close()

    def emit(self, record: logging.LogRecord) -> None:
        """
        Put a log record on the queue.
        """
        try:
            self.enqueue(record)
        except queue.Full:
            logging.getLogger(__name__).debug(
                "the log queue is full, dropping a record"
            )
