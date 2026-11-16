"""Keep tests off the user's real conversation log."""

import pytest


@pytest.fixture(autouse=True)
def _private_conversation_log(tmp_path, monkeypatch):
    from src.memory import conversation_log

    if conversation_log._log is None or conversation_log._log.dir != tmp_path:
        conversation_log.set_conversation_log(
            conversation_log.ConversationLog(tmp_path / "conversations")
        )
    yield
    conversation_log.set_conversation_log(None)
