"""Log filters.

What is available:
- redacting sensitive information
- filtering by level
- filtering by module
"""

import logging
import re
from typing import Optional


class SensitiveDataFilter(logging.Filter):
    """
    Redacts sensitive data from log records.
    """

    # the field names treated as sensitive by default
    DEFAULT_PATTERNS = [
        "password",
        "passwd",
        "pwd",
        "secret",
        "token",
        "api_key",
        "apikey",
        "api-key",
        "access_token",
        "refresh_token",
        "authorization",
        "auth",
        "credential",
        "private_key",
        "privatekey",
        "secret_key",
        "secretkey",
    ]

    # regexes for the common shapes sensitive data takes
    REGEX_PATTERNS = [
        # JWT Token
        (re.compile(r"eyJ[A-Za-z0-9_-]*\.eyJ[A-Za-z0-9_-]*\.[A-Za-z0-9_-]*"), "[JWT]"),
        # Bearer Token
        (re.compile(r"Bearer\s+[A-Za-z0-9_-]+", re.IGNORECASE), "Bearer [REDACTED]"),
        # API Keys (common formats)
        (re.compile(r"sk-[A-Za-z0-9]{32,}"), "[API_KEY]"),
        (re.compile(r"pk-[A-Za-z0-9]{32,}"), "[API_KEY]"),
        # Credit card numbers
        (re.compile(r"\b\d{4}[-\s]?\d{4}[-\s]?\d{4}[-\s]?\d{4}\b"), "[CARD]"),
        # Email addresses (partial mask)
        (
            re.compile(r"\b([A-Za-z0-9._%+-]+)@([A-Za-z0-9.-]+\.[A-Z|a-z]{2,})\b"),
            lambda m: f"{m.group(1)[:2]}***@{m.group(2)}",
        ),
        # Phone numbers (Chinese format)
        (
            re.compile(r"\b1[3-9]\d{9}\b"),
            lambda m: m.group()[:3] + "****" + m.group()[-4:],
        ),
        # IP addresses (internal only)
        (
            re.compile(r"\b(10\.\d{1,3}\.\d{1,3}\.\d{1,3})\b"),
            "[INTERNAL_IP]",
        ),
        (
            re.compile(r"\b(192\.168\.\d{1,3}\.\d{1,3})\b"),
            "[INTERNAL_IP]",
        ),
    ]

    def __init__(
        self,
        name: str = "",
        patterns: Optional[list[str]] = None,
        mask: str = "***",
        enable_regex: bool = True,
    ) -> None:
        super().__init__(name)
        self.patterns = patterns or self.DEFAULT_PATTERNS
        self.mask = mask
        self.enable_regex = enable_regex
        # build the field-matching regex
        pattern_str = "|".join(re.escape(p) for p in self.patterns)
        self._field_pattern = re.compile(
            rf'(["\']?)({pattern_str})(["\']?\s*[:=]\s*)(["\']?)([^"\'\s,}}]+)(["\']?)',
            re.IGNORECASE,
        )

    def filter(self, record: logging.LogRecord) -> bool:
        """
        Filter a record, redacting anything sensitive.
        """
        # the message
        if record.msg:
            record.msg = self._mask_sensitive(str(record.msg))

        # the arguments
        if record.args:
            if isinstance(record.args, dict):
                record.args = {
                    k: self._mask_sensitive(str(v)) if isinstance(v, str) else v
                    for k, v in record.args.items()
                }
            elif isinstance(record.args, tuple):
                record.args = tuple(
                    self._mask_sensitive(str(arg)) if isinstance(arg, str) else arg
                    for arg in record.args
                )

        return True

    def _mask_sensitive(self, text: str) -> str:
        """
        Redact the sensitive information in some text.
        """
        if not text:
            return text

        result = text

        # redact by field name
        result = self._field_pattern.sub(
            lambda m: f"{m.group(1)}{m.group(2)}{m.group(3)}{m.group(4)}{self.mask}{m.group(6)}",
            result,
        )

        # redact by pattern
        if self.enable_regex:
            for pattern, replacement in self.REGEX_PATTERNS:
                if callable(replacement):
                    result = pattern.sub(replacement, result)
                else:
                    result = pattern.sub(replacement, result)

        return result


class DuplicateFilter(logging.Filter):
    """
    Suppresses log messages that repeat in quick succession.
    """

    def __init__(
        self,
        name: str = "",
        suppress_seconds: float = 5.0,
    ) -> None:
        super().__init__(name)
        self.suppress_seconds = suppress_seconds
        self._last_log: dict[str, float] = {}

    def filter(self, record: logging.LogRecord) -> bool:
        """
        Filter out a repeated message.
        """
        import time

        now = time.time()
        key = f"{record.name}:{record.levelno}:{record.msg}"

        last_time = self._last_log.get(key, 0)
        if now - last_time < self.suppress_seconds:
            return False

        self._last_log[key] = now

        # prune the old entries periodically
        if len(self._last_log) > 10000:
            cutoff = now - self.suppress_seconds * 2
            self._last_log = {k: v for k, v in self._last_log.items() if v > cutoff}

        return True
