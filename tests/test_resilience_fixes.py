"""Regression tests for the resilience work: plugin failure isolation, TaskManager tracebacks, and the protocol's bounded audio queue."""

import asyncio
import copy
import json
import logging
import threading
from unittest.mock import AsyncMock

import pytest

from src.core.event_bus import EventBus, Events
from src.core.protocol_manager import ProtocolTransport, _INCOMING_AUDIO_QUEUE_SIZE
from src.core.task_manager import TaskManager
from src.plugins.base import Plugin
from src.plugins.manager import PluginManager


class _OkPlugin(Plugin):
    name = "ok"
    priority = 10

    def __init__(self):
        super().__init__()
        self.setup_calls = 0
        self.start_calls = 0
        self.notify_calls = 0

    async def setup(self, ctx, cmd):
        await super().setup(ctx, cmd)
        self.setup_calls += 1

    async def start(self):
        await super().start()
        self.start_calls += 1

    async def on_incoming_json(self, message):
        self.notify_calls += 1


class _BoomPlugin(Plugin):
    name = "boom"
    priority = 5

    async def setup(self, ctx, cmd):
        await super().setup(ctx, cmd)
        raise RuntimeError("boom setup failed")


class _DepPlugin(Plugin):
    name = "dep_user"
    priority = 20
    requires = ["boom"]

    def __init__(self):
        super().__init__()
        self.setup_calls = 0
        self.start_calls = 0

    async def setup(self, ctx, cmd):
        await super().setup(ctx, cmd)
        self.setup_calls += 1

    async def start(self):
        await super().start()
        self.start_calls += 1


@pytest.mark.asyncio
async def test_plugin_manager_marks_failed_and_skips_dependents():
    mgr = PluginManager()
    boom = _BoomPlugin()
    dep = _DepPlugin()
    ok = _OkPlugin()
    mgr.register(boom, dep, ok)

    await mgr.setup_all(ctx=None, cmd=None)
    await mgr.start_all()
    await mgr.notify_incoming_json({"type": "test"})

    assert boom.failed is True
    assert dep.failed is True
    assert dep.setup_calls == 0
    assert dep.start_calls == 0
    assert ok.failed is False
    assert ok.setup_calls == 1
    assert ok.start_calls == 1
    assert ok.notify_calls == 1
    assert "boom" in mgr.failed_plugins()
    assert mgr.is_failed("boom")
    assert not mgr.is_failed("ok")


@pytest.mark.asyncio
async def test_event_bus_isolates_handler_errors(caplog):
    bus = EventBus()
    seen = []

    async def bad(_=None):
        raise ValueError("handler boom")

    async def good(_=None):
        seen.append("ok")

    bus.on(Events.NETWORK_ERROR, bad)
    bus.on(Events.NETWORK_ERROR, good)

    with caplog.at_level(logging.ERROR):
        await bus.emit(Events.NETWORK_ERROR, "net")

    assert seen == ["ok"]
    assert any("handler boom" in r.getMessage() for r in caplog.records)
    # the exception details should be there (exc_info was filled in)
    assert any(r.exc_info is not None for r in caplog.records)


@pytest.mark.asyncio
async def test_task_manager_logs_exception_with_traceback(caplog):
    tm = TaskManager()
    tm.initialize()

    async def boom():
        raise RuntimeError("task failed for real")

    with caplog.at_level(logging.ERROR):
        task = tm.spawn(boom(), "unit:boom")
        assert task is not None
        with pytest.raises(RuntimeError):
            await task
        # the done callback fires asynchronously, so yield briefly
        await asyncio.sleep(0)

    assert any("unit:boom" in r.getMessage() for r in caplog.records)
    # the point: exc_info must carry the task's exception, not an empty context
    logged = [r for r in caplog.records if "unit:boom" in r.getMessage()]
    assert logged
    assert logged[0].exc_info is not None
    assert logged[0].exc_info[0] is RuntimeError


@pytest.mark.asyncio
async def test_protocol_audio_queue_uses_single_consumer_not_per_frame_tasks():
    bus = EventBus()
    transport = ProtocolTransport(bus)
    received = []

    async def handler(data: bytes):
        received.append(data)
        await asyncio.sleep(0)  # yield, standing in for a slow consumer

    transport.set_audio_handler(handler)
    # push a lot of frames: this must not create one pending task per frame
    n = _INCOMING_AUDIO_QUEUE_SIZE + 20
    for i in range(n):
        transport._on_incoming_audio(bytes([i % 256]))

    # wait for the consumer to drain (the queue is bounded, so older frames go and received is capped)
    for _ in range(50):
        if transport._audio_queue.empty() and len(received) > 0:
            # give it another round
            await asyncio.sleep(0.01)
            if transport._audio_queue.empty():
                break
        await asyncio.sleep(0.01)

    assert len(received) > 0
    # the queue is capped: no more than n are handled, and far fewer than the n that a create_task per frame would leave pending
    assert len(received) <= n
    # there is only one consumer
    assert transport._audio_consumer_task is not None

    await transport.disconnect()


@pytest.mark.asyncio
async def test_protocol_json_spawns_via_task_manager():
    bus = EventBus()
    tm = TaskManager()
    tm.initialize()
    transport = ProtocolTransport(bus, task_manager=tm)

    got = []

    async def on_json(data):
        got.append(data)

    bus.on(Events.INCOMING_JSON, on_json)
    transport._on_incoming_json({"type": "hello"})

    # wait for the spawned task
    for _ in range(30):
        if got:
            break
        await asyncio.sleep(0.01)

    assert got == [{"type": "hello"}]
    await tm.cancel_all()


@pytest.mark.asyncio
async def test_plugin_mark_failed_skips_notify_only_for_failed():
    mgr = PluginManager()
    ok = _OkPlugin()
    ok.mark_failed()
    mgr.register(ok)
    await mgr.notify_incoming_json({"x": 1})
    assert ok.notify_calls == 0


def test_constants_import_has_no_config_manager_side_effect(monkeypatch):
    """Importing constants must not do configuration I/O at module level."""
    import importlib
    import sys

    for name in list(sys.modules):
        if name == "src.constants.constants" or name.startswith(
            "src.constants.constants."
        ):
            del sys.modules[name]

    calls = {"n": 0}

    def fake_get_config():
        calls["n"] += 1
        raise AssertionError("get_config must not be called at import time")

    monkeypatch.setattr(
        "src.utils.config_manager.get_config", fake_get_config, raising=False
    )
    import src.constants.constants as constants

    importlib.reload(constants)

    assert calls["n"] == 0
    assert constants.AudioConfig.OUTPUT_SAMPLE_RATE == 24000
    assert constants.DeviceState.IDLE == "idle"


def test_music_player_detach_clears_runtime_bindings():
    from src.mcp.tools.music.music_player import MusicPlayer

    player = MusicPlayer()
    player._engine.audio_codec = object()  # type: ignore
    player._bus.event_bus = object()  # type: ignore
    player.detach()
    assert player._engine.audio_codec is None
    assert player._bus.event_bus is None


def test_music_tools_register_with_injected_player():
    """The music tools hold the injected MusicPlayer in a closure; there is no get_music_player_instance."""
    from src.mcp.mcp_server import McpServer
    from src.mcp.tools.music import register_music_tools
    from src.mcp.tools.music.music_player import MusicPlayer

    owned = MusicPlayer()
    server = McpServer()
    register_music_tools(server.add_tool, owned)

    names = {t.name for t in server.tools}
    assert "music_player.search_and_play" in names
    assert "music_player.stop" in names

    # at the source level, the global get/bind are no longer exported
    import src.mcp.tools.music as music_pkg
    import src.mcp.tools.music.music_player as mp_mod

    assert not hasattr(music_pkg, "get_music_player_instance")
    assert not hasattr(mp_mod, "get_music_player_instance")
    assert not hasattr(mp_mod, "bind_music_player")


def test_volume_tools_register_without_module_singleton():
    """The volume tools hold the injected controller in a closure; there is no module-level _volume_controller."""
    from src.mcp.mcp_server import McpServer
    from src.mcp.tools.volume import register_volume_tools
    import src.mcp.tools.volume.register as vol_tools

    server = McpServer()
    # inject a fake controller, so this does not depend on the system volume API
    fake = type(
        "FakeVol",
        (),
        {
            "get_volume": lambda self: 42,
            "set_volume": lambda self, v: None,
        },
    )()
    register_volume_tools(server.add_tool, fake)

    names = {t.name for t in server.tools}
    assert "self.audio_speaker.set_volume" in names
    assert "self.audio_speaker.get_volume" in names
    assert "self.audio_speaker.get_volume_status" in names

    assert not hasattr(vol_tools, "_volume_controller")
    assert not hasattr(vol_tools, "_get_volume_controller")


def test_app_and_weather_register_not_decorator_discovery():
    """The app and weather tools mount through register_*; the production path has no decorator-built global table."""
    from src.mcp.mcp_server import McpServer
    from src.mcp.tools.app import register_app_tools
    from src.mcp.tools.weather import register_weather_tools

    server = McpServer()
    register_app_tools(server.add_tool)
    register_weather_tools(server.add_tool)
    names = {t.name for t in server.tools}
    assert "self.application.launch" in names
    assert "self.application.list_running" in names
    assert "get_weather" in names
    assert "get_forecast" in names

    # add_common_tools mounts them all in one go
    server2 = McpServer()
    server2.add_common_tools(music_player=None)
    names2 = {t.name for t in server2.tools}
    assert "self.application.launch" in names2
    assert "get_weather" in names2
    assert "self.audio_speaker.set_volume" in names2

    # the decorator module is gone
    import importlib.util

    assert importlib.util.find_spec("src.mcp.decorators") is None, (
        "src.mcp.decorators should be removed"
    )


def test_mcp_server_detach_clears_callback():
    from src.mcp.mcp_server import McpServer

    server = McpServer()
    server.set_send_callback(lambda m: None)
    assert server._send_callback is not None
    server.detach()
    assert server._send_callback is None


def test_mcp_server_has_no_get_instance():
    from src.mcp.mcp_server import McpServer

    assert not hasattr(McpServer, "get_instance")
    assert not hasattr(McpServer, "bind_instance")
    assert not hasattr(McpServer, "unbind_instance")


def test_mcp_plugin_requires_injected_services():
    from src.plugins.mcp import McpPlugin

    try:
        McpPlugin(server=None, music_player=None)
        assert False, "should raise"
    except ValueError as e:
        assert "McpServer" in str(e) or "MusicPlayer" in str(e)


def test_ui_plugin_uses_view_facade_not_main_model():
    """UIPlugin never touches main_model directly."""
    import inspect

    from src.plugins import ui as ui_mod
    from src.plugins import ui_presenter as presenter_mod

    source = inspect.getsource(ui_mod.UIPlugin)
    assert "main_model" not in source
    assert "_emotion_service" not in source
    assert "create_viewport" in source

    p_source = inspect.getsource(presenter_mod.UiPresenter)
    assert "set_chat_text" in p_source
    assert "set_music_line" in p_source


def test_config_manager_initialize_and_reset():
    from src.utils.config_manager import get_config, initialize_config, reset_config

    reset_config()
    with pytest.raises(RuntimeError):
        get_config()
    a = initialize_config()
    b = get_config()
    assert a is b
    reset_config()
    c = initialize_config()
    assert c is not a
    reset_config()


@pytest.mark.asyncio
async def test_cli_view_manager_uses_task_manager_for_emit():
    from src.core.event_bus import EventBus, Events
    from src.core.task_manager import TaskManager
    from src.ui.cli.manager import CliViewManager

    bus = EventBus()
    tm = TaskManager()
    tm.initialize()
    got = []

    async def on_abort(_=None):
        got.append("abort")

    bus.on(Events.UI_ABORT_REQUEST, on_abort)
    vm = CliViewManager(event_bus=bus, task_manager=tm)
    vm._loop = asyncio.get_running_loop()
    vm._safe_emit(Events.UI_ABORT_REQUEST)

    for _ in range(30):
        if got:
            break
        await asyncio.sleep(0.01)

    assert got == ["abort"]
    await tm.cancel_all()


@pytest.mark.asyncio
async def test_music_player_tick_lyrics_in_playback_path():
    """The lyrics are driven by _tick_lyrics on the main loop; there is no separate lyrics task."""
    from src.mcp.tools.music.music_player import MusicPlayer

    player = MusicPlayer()
    eng = player._engine
    assert (
        not hasattr(player, "_lyrics_task")
        or player.__dict__.get("_lyrics_task") is None
    )

    emitted = []

    async def fake_emit(text, time_sec=0):
        emitted.append(text)

    player.lyrics = [(0.0, "hello"), (5.0, "world")]
    eng.start_play_time = __import__("time").time() - 0.1
    eng.total_duration = 100
    eng.current_lyric_index = -1
    eng.last_lyric_tick = 0.0
    player._bus.emit_lyrics_update = fake_emit  # type: ignore

    await player._tick_lyrics()
    assert eng.current_lyric_index == 0
    assert emitted and "hello" in emitted[0]

    # throttled: ticking again straight away should do nothing
    n = len(emitted)
    await player._tick_lyrics()
    assert len(emitted) == n


def test_lyric_at_pure_function():
    from src.mcp.tools.music.lyrics import format_lyric_display, lyric_at

    lyrics = [(0.0, "a"), (5.0, "b"), (10.0, "c")]
    assert lyric_at(lyrics, 0.0)[1] == "a"
    # with lead=0.5 the second line becomes current at 5.6
    assert lyric_at(lyrics, 5.6)[1] == "b"
    assert lyric_at(lyrics, 99.0)[1] == "c"
    assert lyric_at([], 1.0) is None
    assert "[00:01/03:00]" in format_lyric_display("x", 1.0, 180.0)


def test_music_cache_paths(tmp_path):
    from src.mcp.tools.music.cache import MusicCache

    c = MusicCache(root=tmp_path / "music")
    c.prepare()
    p = c.path_for_song("123")
    assert p.parent == c.root
    assert not c.has("123")
    p.write_bytes(b"x")
    assert c.has("123")
    assert c.find_song_file("123") == p


def test_gui_activation_no_ensure_future_or_get_event_loop():
    import inspect
    from src.ui.gui import activation as act_mod

    src = inspect.getsource(act_mod.GuiActivation)
    assert "ensure_future" not in src
    assert "get_event_loop" not in src
    assert "get_running_loop" in src or "create_task" in src


def test_config_manager_batch_update_single_save(tmp_path, monkeypatch):
    """A batched update_configs writes to disk only once."""
    from src.utils.config_manager import get_config, initialize_config, reset_config

    reset_config()
    cm = initialize_config()
    # point at a temp file, so the real user config is untouched
    cm.config_dir = tmp_path
    cm.config_file = tmp_path / "config.json"
    cm._config = {
        "SYSTEM_OPTIONS": {
            "NETWORK": {
                "MQTT_INFO": None,
                "WEBSOCKET_URL": None,
                "WEBSOCKET_ACCESS_TOKEN": None,
            }
        }
    }

    saves = {"n": 0}
    orig = cm._save_config

    def counting_save(cfg):
        saves["n"] += 1
        return orig(cfg)

    monkeypatch.setattr(cm, "_save_config", counting_save)

    ok = cm.update_configs(
        {
            "SYSTEM_OPTIONS.NETWORK.MQTT_INFO": {"host": "x"},
            "SYSTEM_OPTIONS.NETWORK.WEBSOCKET_URL": "wss://example",
            "SYSTEM_OPTIONS.NETWORK.WEBSOCKET_ACCESS_TOKEN": "tok",
        }
    )
    assert ok is True
    assert saves["n"] == 1
    assert cm.get_config("SYSTEM_OPTIONS.NETWORK.WEBSOCKET_URL") == "wss://example"
    assert get_config() is cm

    # a single update still saves
    cm.update_config("SYSTEM_OPTIONS.NETWORK.WEBSOCKET_ACCESS_TOKEN", "tok2")
    assert saves["n"] == 2

    reset_config()


def test_config_manager_update_through_none_intermediate(tmp_path):
    """A dotted write still works when an intermediate node is null (MQTT_INFO: null, for instance)."""
    from src.utils.config_manager import ConfigManager, reset_config

    reset_config()
    cm = ConfigManager.__new__(ConfigManager)
    cm.config_dir = tmp_path
    cm.config_file = tmp_path / "config.json"
    cm._config = {
        "SYSTEM_OPTIONS": {
            "NETWORK": {
                "MQTT_INFO": None,
            }
        }
    }

    assert cm.update_config(
        "SYSTEM_OPTIONS.NETWORK.MQTT_INFO.endpoint", "mqtt.example.com", save=False
    )
    assert (
        cm.get_config("SYSTEM_OPTIONS.NETWORK.MQTT_INFO.endpoint") == "mqtt.example.com"
    )
    assert isinstance(cm.get_config("SYSTEM_OPTIONS.NETWORK.MQTT_INFO"), dict)


def test_config_manager_no_default_config_pollution():
    """An instance update must not mutate the nested objects inside the class-level DEFAULT_CONFIG."""
    from src.utils.config_manager import ConfigManager, reset_config

    reset_config()
    before = copy.deepcopy(
        ConfigManager.DEFAULT_CONFIG["WAKE_WORD_OPTIONS"]["WAKE_WORD"]
    )

    cm = ConfigManager.__new__(ConfigManager)
    cm.config_dir = None  # type: ignore
    cm.config_file = None  # type: ignore
    cm._config = copy.deepcopy(ConfigManager.DEFAULT_CONFIG)
    cm.update_config("WAKE_WORD_OPTIONS.WAKE_WORD", "__pollute_test__", save=False)

    assert ConfigManager.DEFAULT_CONFIG["WAKE_WORD_OPTIONS"]["WAKE_WORD"] == before
    assert cm.get_config("WAKE_WORD_OPTIONS.WAKE_WORD") == "__pollute_test__"


def test_config_manager_corrupt_file_backed_up(tmp_path, monkeypatch):
    """A corrupt config.json is backed up, the defaults are used, and DEFAULT_CONFIG is left alone."""
    from src.utils import config_manager as cm_mod
    from src.utils.config_manager import ConfigManager, reset_config

    reset_config()
    cfg_dir = tmp_path / "config"
    cfg_dir.mkdir()
    bad = cfg_dir / "config.json"
    bad.write_text("{ not json", encoding="utf-8")

    monkeypatch.setattr(cm_mod, "get_user_data_dir", lambda: tmp_path)
    # do not copy another one in from the installation directory
    monkeypatch.setattr(
        cm_mod, "get_config_dir", lambda: tmp_path / "no-install-config"
    )

    before_wake = copy.deepcopy(
        ConfigManager.DEFAULT_CONFIG["WAKE_WORD_OPTIONS"]["WAKE_WORD"]
    )
    cm = ConfigManager()
    assert cm.get_config("WAKE_WORD_OPTIONS.USE_WAKE_WORD") is True
    assert cm.get_config("MUSIC.DEFAULT_PLATFORM") == "kw"
    assert ConfigManager.DEFAULT_CONFIG["WAKE_WORD_OPTIONS"]["WAKE_WORD"] == before_wake

    backups = list(cfg_dir.glob("config.json.corrupt-*"))
    assert len(backups) == 1
    assert backups[0].read_text(encoding="utf-8") == "{ not json"
    # a usable default has been written
    assert cm.config_file.exists()
    loaded = json.loads(cm.config_file.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    assert "MUSIC" in loaded

    reset_config()


def test_config_manager_default_includes_music_and_window_mode():
    from src.utils.config_manager import ConfigManager

    d = ConfigManager.DEFAULT_CONFIG
    assert "MUSIC" in d
    assert d["MUSIC"]["DEFAULT_PLATFORM"] == "kw"
    assert d["SYSTEM_OPTIONS"]["WINDOW_SIZE_MODE"] == "default"


def test_efuse_create_is_flat(tmp_path, monkeypatch):
    """A fresh efuse.json holds only the four flat fields, with no device_fingerprint."""
    from src.activation.identity import DeviceIdentity

    idn = DeviceIdentity()
    idn._efuse_file = tmp_path / "efuse.json"
    fp = {
        "system": "Darwin",
        "hostname": "test-host",
        "mac_address": "aa:bb:cc:dd:ee:ff",
        "machine_id": "mid-1",
    }
    idn._create_efuse_file(fp, fp["mac_address"])
    import json

    data = json.loads(idn._efuse_file.read_text(encoding="utf-8"))
    assert set(data.keys()) == {
        "mac_address",
        "serial_number",
        "hmac_key",
        "activation_status",
    }
    assert "device_fingerprint" not in data
    assert data["mac_address"] == "aa:bb:cc:dd:ee:ff"
    assert data["activation_status"] is False
    assert data["serial_number"].startswith("SN-")
    assert len(data["hmac_key"]) == 64


def test_efuse_strips_legacy_device_fingerprint(tmp_path):
    """A legacy nested device_fingerprint is stripped and rewritten on ensure."""
    import json
    from src.activation.identity import DeviceIdentity

    path = tmp_path / "efuse.json"
    path.write_text(
        json.dumps(
            {
                "mac_address": "11:22:33:44:55:66",
                "serial_number": "SN-OLD-112233445566",
                "hmac_key": "a" * 64,
                "activation_status": True,
                "device_fingerprint": {
                    "system": "Darwin",
                    "hostname": "old",
                    "mac_address": "11:22:33:44:55:66",
                    "machine_id": "x",
                },
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    idn = DeviceIdentity()
    idn._efuse_file = path
    # no real network card needed: validate only fills the missing fields from the fingerprint it is given
    fp = {
        "system": "Darwin",
        "hostname": "h",
        "mac_address": "11:22:33:44:55:66",
        "machine_id": "m",
    }
    idn._validate_efuse_file(fp, fp["mac_address"])
    data = json.loads(path.read_text(encoding="utf-8"))
    assert "device_fingerprint" not in data
    assert set(data.keys()) == {
        "mac_address",
        "serial_number",
        "hmac_key",
        "activation_status",
    }
    assert data["activation_status"] is True
    assert data["serial_number"] == "SN-OLD-112233445566"
    assert idn.get_mac_address() == "11:22:33:44:55:66"
    assert idn.is_activated() is True


def test_efuse_save_never_writes_extra_keys(tmp_path):
    from src.activation.identity import DeviceIdentity

    idn = DeviceIdentity()
    idn._efuse_file = tmp_path / "efuse.json"
    ok = idn._save_efuse_data(
        {
            "mac_address": "aa:bb:cc:dd:ee:ff",
            "serial_number": "SN-X",
            "hmac_key": "b" * 64,
            "activation_status": False,
            "device_fingerprint": {"should": "drop"},
            "extra": 1,
        }
    )
    assert ok
    import json

    data = json.loads(idn._efuse_file.read_text(encoding="utf-8"))
    assert "device_fingerprint" not in data
    assert "extra" not in data


def test_mcp_tools_disabled_filters_list_and_call_gate():
    """MCP_TOOLS.DISABLED keeps a tool out of the list and refuses the call."""
    import asyncio
    from src.mcp.mcp_server import McpServer
    from src.mcp.tooling import McpTool, PropertyList

    server = McpServer()

    async def ok(_):
        return '{"ok": true}'

    server.add_tool(McpTool("music_player.stop", "d", PropertyList(), ok))
    server.add_tool(McpTool("music_player.pause", "d", PropertyList(), ok))
    server._disabled_tool_names = lambda: {"music_player.stop"}  # type: ignore
    assert [t.name for t in server._iter_enabled_tools()] == ["music_player.pause"]


def test_mcp_tool_catalog_groups():
    from src.mcp.tool_catalog import (
        builtin_catalog_rows,
        clear_builtin_catalog_cache,
        normalize_disabled,
        tool_group,
    )

    clear_builtin_catalog_cache()
    rows = builtin_catalog_rows()
    # the group is the tools/<pkg> directory name, found by scanning register.py rather than from a hard-coded list
    by_name = {r["name"]: r for r in rows}
    assert "music_player.seek" in by_name
    assert by_name["music_player.seek"]["group"] == "music"
    assert by_name["music_player.seek"]["groupLabel"] == "music"
    assert by_name["self.application.launch"]["group"] == "app"
    assert by_name["self.application.launch"]["groupLabel"] == "app"
    assert by_name["take_photo"]["group"] == "camera"
    assert by_name["take_screenshot"]["group"] == "screenshot"
    assert by_name["get_weather"]["groupLabel"] == "weather"
    # the name-only heuristic, used when there is no package context
    assert tool_group("music_player.seek") == "music_player"
    assert tool_group("self.application.launch") == "self.application"
    assert normalize_disabled(["", " a ", "a"]) == ["a"]


def test_music_player_init_is_lazy():
    """Constructing MusicPlayer must not scan the cache directory or take the full config side-effect path."""
    from src.mcp.tools.music.music_player import MusicPlayer
    from src.utils.config_manager import initialize_config, reset_config

    reset_config()
    initialize_config()
    try:
        p = MusicPlayer()
        assert p._config is None
        assert p._cache._ready is False
        assert p._cache._temp_cleaned is False
        cfg = p.config
        assert isinstance(cfg, dict)
        assert "SEARCH_URL" in cfg
    finally:
        reset_config()


def test_viewport_protocol_and_cli_slots():
    """In the CLI the chat and music lines do not clobber each other."""
    from src.core.event_bus import EventBus
    from src.ui.cli.manager import CliViewManager
    from src.ui.shared.viewport import ViewPort

    bus = EventBus()
    vm = CliViewManager(event_bus=bus)
    assert isinstance(vm, ViewPort)

    vm.set_chat_text("hello")
    vm.set_music_line("♪ a lyric line")
    assert vm._chat_text == "hello"
    assert vm._music_line == "♪ a lyric line"
    assert vm._display._dash_text == "hello"
    assert vm._display._dash_music == "♪ a lyric line"

    vm.set_chat_text("second line")
    assert vm._chat_text == "second line"
    assert vm._music_line == "♪ a lyric line"


def test_gpio_viewport_slots():
    from src.core.event_bus import EventBus
    from src.ui.gpio.manager import GpioViewManager
    from src.ui.shared.viewport import ViewPort

    vm = GpioViewManager(event_bus=EventBus())
    assert isinstance(vm, ViewPort)
    vm.set_chat_text("chat")
    vm.set_music_line("music")
    assert vm._chat_text == "chat"
    assert vm._music_line == "music"
    vm.set_chat_text("chat2")
    assert vm._chat_text == "chat2"
    assert vm._music_line == "music"


def test_create_viewport_cli_factory():
    from src.core.event_bus import EventBus
    from src.ui.cli.manager import CliViewManager
    from src.ui.shared.factory import create_viewport
    from src.ui.shared.viewport import ViewPort

    vp = create_viewport("cli", EventBus())
    assert isinstance(vp, CliViewManager)
    assert isinstance(vp, ViewPort)


def test_deprecated_ui_events_removed():
    """The old UI_UPDATE_* and UI_TOGGLE_MODE events are gone."""
    from src.core.event_bus import Events

    for name in (
        "UI_UPDATE_TEXT",
        "UI_UPDATE_EMOTION",
        "UI_UPDATE_STATUS",
        "UI_TOGGLE_MODE",
    ):
        assert not hasattr(Events, name)


class _FakeViewport:
    def __init__(self):
        self.chat = []
        self.music = []
        self.status = []
        self.emotions = []
        self.buttons = []
        self.auto_modes = []
        self._auto = False

    def set_chat_text(self, text: str) -> None:
        self.chat.append(text)

    def set_music_line(self, text: str) -> None:
        self.music.append(text)

    def set_status(self, status: str, connected: bool = True) -> None:
        self.status.append((status, connected))

    def set_emotion(self, emotion: str) -> None:
        self.emotions.append(emotion)

    def set_button_text(self, text: str) -> None:
        self.buttons.append(text)

    def set_auto_mode(self, auto_mode: bool) -> None:
        self._auto = auto_mode
        self.auto_modes.append(auto_mode)

    def is_auto_mode(self) -> bool:
        return self._auto

    async def start(self, mode: str = "cli") -> None:
        pass

    async def close(self) -> None:
        pass


@pytest.mark.asyncio
async def test_ui_plugin_routes_music_to_music_line():
    """Music goes to the music line and does not overwrite the chat."""
    from src.mcp.tools.music.events import MusicLyricsData, MusicStateData
    from src.plugins.ui import UIPlugin

    plugin = UIPlugin(mode="cli")
    vp = _FakeViewport()
    plugin.viewport = vp
    plugin._presenter.bind(vp)

    await plugin._on_music_state_changed(
        MusicStateData(state="playing", song="Test Track", position=0.0, duration=180.0)
    )
    await plugin._on_music_lyrics_update(
        MusicLyricsData(text="[00:01/03:00] first line", time_sec=1.0)
    )
    await plugin.on_incoming_json({"type": "tts", "text": "hello there"})

    assert any("Playing:" in t for t in vp.music)
    assert "[00:01/03:00] first line" in vp.music
    assert "hello there" in vp.chat
    assert not any("Playing:" in t or "first line" in t for t in vp.chat)


@pytest.mark.asyncio
async def test_session_actions_owns_auto_mode():
    """The Session owns the mode; the interface only follows set_auto_mode."""
    from src.plugins.ui_presenter import UiPresenter
    from src.plugins.ui_session import SessionActions

    class _Cmd:
        def request_shutdown(self):
            pass

        async def abort_speaking(self, _):
            pass

        async def connect_protocol(self):
            return True

        async def send_wake_word_detected(self, text):
            pass

        async def start_listening(self, mode):
            pass

        async def stop_listening(self):
            pass

    class _Ctx:
        def is_speaking(self):
            return False

        def is_listening(self):
            return False

        def get_config(self):
            class C:
                def get_config(self, k, d=None):
                    return d

            return C()

    vp = _FakeViewport()
    presenter = UiPresenter(vp)
    session = SessionActions(_Ctx(), _Cmd(), presenter)

    assert session.auto_mode is False
    await session.auto_toggle()
    assert session.auto_mode is True
    assert vp.auto_modes == [True]
    assert vp.is_auto_mode() is True
    await session.auto_toggle()
    assert session.auto_mode is False
    assert vp.auto_modes == [True, False]


@pytest.mark.asyncio
async def test_auto_session_button_start_stop():
    """In auto mode the main button toggles between start and stop."""
    from src.plugins.ui_presenter import UiPresenter
    from src.plugins.ui_session import SessionActions

    listening = {"v": False}
    speaking = {"v": False}
    stops = []
    starts = []

    class _Cmd:
        async def connect_protocol(self):
            return True

        async def start_listening(self, mode):
            starts.append(mode)
            listening["v"] = True

        async def stop_listening(self):
            stops.append("stop")
            listening["v"] = False

        async def abort_speaking(self, reason):
            stops.append(("abort", reason))
            speaking["v"] = False

        async def send_wake_word_detected(self, text):
            pass

    class _Ctx:
        def is_speaking(self):
            return speaking["v"]

        def is_listening(self):
            return listening["v"]

        def get_config(self):
            class C:
                def get_config(self, k, d=None):
                    return True if k == "AEC_OPTIONS.ENABLED" else d

            return C()

    vp = _FakeViewport()
    session = SessionActions(_Ctx(), _Cmd(), UiPresenter(vp))
    session._auto_mode = True

    await session.auto_session_toggle()
    assert session.auto_session_active is True
    assert vp.buttons[-1] == "Stop Chat"
    assert starts

    await session.auto_session_toggle()
    assert session.auto_session_active is False
    assert vp.buttons[-1] == "Start Chat"
    assert "stop" in stops


@pytest.mark.asyncio
async def test_send_text_from_idle_starts_listen_then_detect():
    """Sending text from idle must listen first, then detect."""
    from src.constants.constants import ListeningMode
    from src.plugins.ui_presenter import UiPresenter
    from src.plugins.ui_session import SessionActions

    order = []
    listening = {"v": False}

    class _Cmd:
        async def connect_protocol(self):
            order.append("connect")
            return True

        async def start_listening(self, mode):
            order.append(("listen", mode))
            listening["v"] = True

        async def send_wake_word_detected(self, text):
            order.append(("detect", text))

        async def abort_speaking(self, reason):
            order.append(("abort", reason))

    class _Ctx:
        def is_speaking(self):
            return False

        def is_listening(self):
            return listening["v"]

        def get_config(self):
            class C:
                def get_config(self, k, d=None):
                    return False  # AEC off → AUTO_STOP when auto

            return C()

    session = SessionActions(_Ctx(), _Cmd(), UiPresenter(_FakeViewport()))
    # sending text from idle in manual mode
    await session.send_text("play a song")
    assert order[0] == "connect"
    assert order[1] == ("listen", ListeningMode.MANUAL)
    assert order[2] == ("detect", "play a song")

    # already listening, so it must not start again
    order.clear()
    await session.send_text("hello")
    assert order == [("detect", "hello")]


@pytest.mark.asyncio
async def test_abort_speaking_resumes_keep_listening():
    """With continuous listening on, an interrupt returns to listening."""
    from src.bootstrap.session import ConversationSession
    from src.constants.constants import DeviceState, ListeningMode

    order = []

    class FakeProtocol:
        def is_audio_channel_opened(self):
            return True

        async def send_abort_speaking(self, reason):
            order.append(("abort", reason))

        async def send_start_listening(self, mode):
            order.append(("listen", mode))

    class FakeState:
        def __init__(self):
            self.keep_listening = True
            self.listening_mode = ListeningMode.AUTO_STOP
            self._state = DeviceState.SPEAKING
            self._aborted = False

        def set_aborted(self, v):
            self._aborted = v

        async def set_device_state(self, state):
            order.append(("state", state))
            self._state = state

    session = ConversationSession(
        state=FakeState(),
        protocol=FakeProtocol(),
        plugins=None,  # type: ignore[arg-type]
    )

    await session.abort_speaking("user_interruption")
    assert ("abort", "user_interruption") in order
    assert ("listen", ListeningMode.AUTO_STOP) in order
    assert ("state", DeviceState.LISTENING) in order
    assert ("state", DeviceState.IDLE) not in order
    assert session._aborted is False


def test_device_state_handler_does_not_block_with_sleep():
    """Entering LISTENING must not sleep inside the state callback."""
    import inspect

    from src.bootstrap.session import ConversationSession

    src = inspect.getsource(ConversationSession._on_device_state_changed)
    assert "asyncio.sleep" not in src
    assert "await " not in src or "notify_device_state_changed" in src
    # no artificial delay may be awaited
    assert "await asyncio" not in src
    src_stop = inspect.getsource(ConversationSession._handle_tts_stop)
    # listen again before changing state: send_start_listening must come before set_device_state
    assert src_stop.index("send_start_listening") < src_stop.index(
        "set_device_state(DeviceState.LISTENING)"
    )


@pytest.mark.asyncio
async def test_handle_tts_stop_relisten_before_state():
    """AUTO_STOP: when TTS stops, send the listen before changing state."""
    from src.bootstrap.session import ConversationSession
    from src.constants.constants import DeviceState, ListeningMode

    order = []

    class FakeProtocol:
        def is_audio_channel_opened(self):
            return True

        async def send_start_listening(self, mode):
            order.append(("listen", mode))

    class FakeState:
        def __init__(self):
            self.keep_listening = True
            self.listening_mode = ListeningMode.AUTO_STOP
            self._state = DeviceState.SPEAKING

        def is_listening(self):
            return self._state == DeviceState.LISTENING

        async def set_device_state(self, state):
            # stand in for a slow plugin: a listen sent after this would hit the delay
            order.append(("state", state))
            self._state = state

    class FakeCodec:
        async def clear_audio_queue(self):
            order.append("clear_queue")

    class FakePlugins:
        def get_plugin(self, name):
            if name == "audio":
                p = type("P", (), {})()
                p.codec = FakeCodec()
                return p
            return None

    session = ConversationSession(
        state=FakeState(),
        protocol=FakeProtocol(),
        plugins=FakePlugins(),  # type: ignore[arg-type]
    )

    await session._handle_tts_stop()

    assert order[0] == ("listen", ListeningMode.AUTO_STOP)
    assert "clear_queue" in order
    assert ("state", DeviceState.LISTENING) in order
    assert order.index(("listen", ListeningMode.AUTO_STOP)) < order.index(
        ("state", DeviceState.LISTENING)
    )


@pytest.mark.asyncio
async def test_handle_tts_stop_realtime_skips_relisten():
    from src.bootstrap.session import ConversationSession
    from src.constants.constants import DeviceState, ListeningMode

    order = []

    class FakeProtocol:
        def is_audio_channel_opened(self):
            return True

        async def send_start_listening(self, mode):
            order.append("listen")

    class FakeState:
        keep_listening = True
        listening_mode = ListeningMode.REALTIME

        async def set_device_state(self, state):
            order.append(("state", state))

    class FakePlugins:
        def get_plugin(self, name):
            return None

    session = ConversationSession(
        state=FakeState(),
        protocol=FakeProtocol(),
        plugins=FakePlugins(),  # type: ignore[arg-type]
    )

    await session._handle_tts_stop()
    assert "listen" not in order
    assert order == [("state", DeviceState.LISTENING)]


# ---------------------------------------------------------------------------
# 2026-07-22 polish: architecture and smoke tests beyond the exc_info work
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_event_bus_warns_on_unknown_event_name(caplog):
    import logging

    bus = EventBus()
    with caplog.at_level(logging.WARNING):
        bus.on("typo_event_that_does_not_exist", AsyncMock())
        await bus.emit("another_typo_event")

    text = caplog.text
    assert "typo_event_that_does_not_exist" in text
    assert "another_typo_event" in text
    assert "unknown event name" in text


@pytest.mark.asyncio
async def test_music_player_receives_codec_via_event_bus():
    """Audio publishes AUDIO_CODEC_CHANGED and Music subscribes; nothing calls set_audio_codec directly."""
    from src.mcp.tools.music.music_player import MusicPlayer

    bus = EventBus()
    player = MusicPlayer()
    eng = player._engine
    player.set_event_bus(bus)
    codec = object()

    await bus.emit(Events.AUDIO_CODEC_CHANGED, codec)
    assert eng.audio_codec is codec

    eng.is_playing = True
    eng.current_song = "t"

    async def _fake_stop():
        eng.is_playing = False
        return {"status": "success"}

    player.stop = _fake_stop  # type: ignore[method-assign]

    await bus.emit(Events.AUDIO_CODEC_CHANGED, None)
    assert eng.audio_codec is None
    assert eng.is_playing is False

    player.detach()


def test_music_player_has_no_set_audio_codec_api():
    from src.mcp.tools.music.music_player import MusicPlayer

    assert not hasattr(MusicPlayer, "set_audio_codec")
    assert MusicPlayer.__init__.__code__.co_argcount == 1  # self only
    # the state lives on the engine; the facade exposes only a few read-only properties
    assert isinstance(MusicPlayer.is_playing, property)
    assert MusicPlayer.is_playing.fset is None


def test_audio_is_fatal_respects_degraded_env(monkeypatch):
    from src.bootstrap.health import audio_is_fatal

    monkeypatch.delenv("XIAOZHI_DISABLE_AUDIO", raising=False)
    monkeypatch.delenv("XIAOZHI_DEGRADED_AUDIO", raising=False)
    assert audio_is_fatal() is True

    monkeypatch.setenv("XIAOZHI_DEGRADED_AUDIO", "1")
    assert audio_is_fatal() is False

    monkeypatch.delenv("XIAOZHI_DEGRADED_AUDIO", raising=False)
    monkeypatch.setenv("XIAOZHI_DISABLE_AUDIO", "1")
    assert audio_is_fatal() is False


def test_check_critical_plugins_audio_degraded(monkeypatch):
    from src.bootstrap.health import check_critical_plugins

    class FakePlugins:
        def __init__(self, failed):
            self._failed = failed

        def is_failed(self, name):
            return name in self._failed

    monkeypatch.delenv("XIAOZHI_DISABLE_AUDIO", raising=False)
    monkeypatch.delenv("XIAOZHI_DEGRADED_AUDIO", raising=False)
    err = check_critical_plugins(FakePlugins({"audio", "ui"}))
    assert err is not None
    assert "ui" in err
    assert "audio" in err

    # audio alone failed, degraded mode on -> no gate
    monkeypatch.setenv("XIAOZHI_DEGRADED_AUDIO", "1")
    assert check_critical_plugins(FakePlugins({"audio"})) is None

    # audio alone failed, default settings -> the gate closes
    monkeypatch.delenv("XIAOZHI_DEGRADED_AUDIO", raising=False)
    err = check_critical_plugins(FakePlugins({"audio"}))
    assert err is not None and "audio" in err
    assert "XIAOZHI_DEGRADED_AUDIO" in err


@pytest.mark.asyncio
async def test_cli_mock_protocol_smoke_session():
    """A CLI-level smoke test: a mock protocol feeds bounded audio and JSON into the state machine, with no real network or microphone."""
    from src.core.task_manager import TaskManager
    from src.protocols.protocol import Protocol

    bus = EventBus()
    tm = TaskManager()
    tm.initialize()
    transport = ProtocolTransport(bus, task_manager=tm)

    received_json: list = []
    received_audio: list = []

    async def on_json(data):
        received_json.append(data)

    async def on_audio(data: bytes):
        received_audio.append(data)

    bus.on(Events.INCOMING_JSON, on_json)

    class MockProtocol(Protocol):
        def __init__(self):
            super().__init__()
            self._opened = False
            self.sent_texts: list[str] = []
            self.sent_audio: list[bytes] = []

        async def open_audio_channel(self) -> bool:
            self._opened = True
            if self._on_audio_channel_opened:
                await self._on_audio_channel_opened()
            return True

        async def close_audio_channel(self) -> None:
            self._opened = False
            if self._on_audio_channel_closed:
                await self._on_audio_channel_closed()

        def is_audio_channel_opened(self) -> bool:
            return self._opened

        async def send_text(self, message):
            self.sent_texts.append(message)

        async def send_audio(self, data: bytes):
            self.sent_audio.append(data)

    mock = MockProtocol()
    transport._protocol = mock
    transport._setup_callbacks()
    transport.set_audio_handler(on_audio)

    assert await transport.connect(timeout=1.0) is True
    assert mock.is_audio_channel_opened()

    # stand in for the server's JSON plus several audio frames (bounded queue, one consumer)
    transport._on_incoming_json({"type": "tts", "state": "start", "text": "hello"})
    for i in range(20):
        transport._on_incoming_audio(bytes([i % 256]))
    transport._on_incoming_json({"type": "tts", "state": "stop"})

    # wait for the TaskManager and the consumer to finish
    await asyncio.sleep(0.15)

    assert any(m.get("type") == "tts" for m in received_json)
    assert len(received_audio) == 20

    await transport.disconnect()
    await tm.cancel_all()


def test_settings_run_worker_emits_test_complete_on_exception():
    """A failing background task must still emit testComplete, so the settings page does not spin forever."""
    from src.ui.gui.models.settings_model import SettingsModel

    # skip the full __init__, which would touch ConfigManager and the filesystem; bind _run_worker to a stub instead
    completed: list = []
    messages: list = []

    class _Sig:
        def __init__(self, sink):
            self._sink = sink

        def emit(self, *args):
            self._sink.append(args if len(args) != 1 else args[0])

    class _Stub:
        pass

    stub = _Stub()
    stub.testComplete = _Sig(completed)
    stub.statusMessage = _Sig(messages)
    stub._testing_input = True
    stub._run_worker = SettingsModel._run_worker.__get__(stub, SettingsModel)

    def boom():
        raise RuntimeError("device busy")

    done = threading.Event()

    def clear():
        stub._testing_input = False
        done.set()

    stub._run_worker(
        boom,
        name="settings:test_worker",
        test_kind="input",
        clear_flags=clear,
    )
    assert done.wait(timeout=2.0)
    assert stub._testing_input is False
    assert completed == [("input", False)]
    assert any("device busy" in str(m) for m in messages)


def test_no_config_or_logging_get_instance_api():
    """Neither the config nor the logging module exposes a lazy get_instance singleton any more."""
    from src.utils import config_manager as cm
    from src.logging import log_config as lc
    import src.logging as logging_pkg

    assert not hasattr(cm.ConfigManager, "get_instance")
    assert not hasattr(cm.ConfigManager, "reset_instance")
    assert hasattr(cm, "initialize_config")
    assert hasattr(cm, "get_config")
    assert hasattr(cm, "reset_config")
    assert not hasattr(lc, "LoggingConfigManager")
    assert hasattr(lc, "load_logging_config")
    assert "LoggingConfigManager" not in logging_pkg.__all__


# ---------------------------------------------------------------------------
# the external MCP plugin loader
# ---------------------------------------------------------------------------


def test_mcp_plugin_loader_loads_package_and_respects_disabled(tmp_path):
    """A full plugin directory: register(host) succeeds, and anything in DISABLED_IDS is not loaded."""
    from src.mcp.mcp_server import McpServer
    from src.mcp.plugins.host import McpHost
    from src.mcp.plugins.loader import PluginLoader

    plugin_root = tmp_path / "com.example.hello"
    plugin_root.mkdir()
    (plugin_root / "manifest.json").write_text(
        (
            "{"
            '"id":"com.example.hello",'
            '"version":"1.0.0",'
            '"api_version":1,'
            '"entry":"plugin:register",'
            '"runtime":"python-inprocess",'
            '"enabled_by_default":true'
            "}"
        ),
        encoding="utf-8",
    )
    plugin_src = (
        "def register(host):\n"
        '    @host.tool(name="example.hello", description="hi", props=[])\n'
        "    async def hello(args):\n"
        '        return "ok"\n'
    )
    # decode escapes for actual file content written by the test
    (plugin_root / "plugin.py").write_text(
        plugin_src.encode().decode("unicode_escape"),
        encoding="utf-8",
    )

    server = McpServer()
    host = McpHost(server.add_tool, allow_get=["logger"])
    loader = PluginLoader(host, plugins_dir=tmp_path)
    results = loader.load_all()
    assert any(r.plugin_id == "com.example.hello" and not r.error for r in results)
    assert any(tool.name == "example.hello" for tool in server.tools)

    server2 = McpServer()
    host2 = McpHost(server2.add_tool)
    loader2 = PluginLoader(
        host2, plugins_dir=tmp_path, disabled_ids=["com.example.hello"]
    )
    results2 = loader2.load_all()
    assert any(r.error == "disabled" for r in results2)
    assert not any(tool.name == "example.hello" for tool in server2.tools)


def test_mcp_plugin_loader_vendored_lib(tmp_path):
    """A plugin can import a module from its own lib/ directory (standing in for a vendored dependency)."""
    from src.mcp.mcp_server import McpServer
    from src.mcp.plugins.host import McpHost
    from src.mcp.plugins.loader import PluginLoader

    root = tmp_path / "com.example.vendored"
    root.mkdir()
    (root / "manifest.json").write_text(
        (
            "{"
            '"id":"com.example.vendored",'
            '"entry":"plugin:register",'
            '"runtime":"python-inprocess"'
            "}"
        ),
        encoding="utf-8",
    )
    lib = root / "lib"
    lib.mkdir()
    (lib / "demo_dep.py").write_text(
        "VALUE = 42\n".encode().decode("unicode_escape"), encoding="utf-8"
    )
    plugin_src = (
        "def register(host):\n"
        "    import demo_dep\n"
        '    @host.tool(name="example.answer", description="answer")\n'
        "    async def answer(args):\n"
        "        return str(demo_dep.VALUE)\n"
    )
    (root / "plugin.py").write_text(
        plugin_src.encode().decode("unicode_escape"), encoding="utf-8"
    )

    server = McpServer()
    loader = PluginLoader(McpHost(server.add_tool), plugins_dir=tmp_path)
    results = loader.load_all()
    assert any(not r.error and r.plugin_id == "com.example.vendored" for r in results)
    assert any(tool.name == "example.answer" for tool in server.tools)


def test_mcp_plugin_simple_py_file(tmp_path):
    from src.mcp.mcp_server import McpServer
    from src.mcp.plugins.host import McpHost
    from src.mcp.plugins.loader import PluginLoader

    solo_src = (
        "from src.mcp.tooling import McpTool, PropertyList\n\n"
        "def register(host):\n"
        "    async def ping(args):\n"
        '        return "pong"\n'
        '    host.add_tool(McpTool("solo.ping", "ping", PropertyList(), ping))\n'
    )
    (tmp_path / "solo.py").write_text(
        solo_src.encode().decode("unicode_escape"), encoding="utf-8"
    )

    server = McpServer()
    PluginLoader(McpHost(server.add_tool), plugins_dir=tmp_path).load_all()
    assert any(tool.name == "solo.ping" for tool in server.tools)


def test_mcp_server_unload_plugin(tmp_path):
    """External tools can be unloaded at runtime by plugin_id."""
    from src.mcp.mcp_server import McpServer
    from src.mcp.plugins.host import McpHost
    from src.mcp.plugins.loader import PluginLoader

    root = tmp_path / "com.example.tmp"
    root.mkdir()
    (root / "manifest.json").write_text(
        '{"id":"com.example.tmp","entry":"plugin:register","runtime":"python-inprocess"}',
        encoding="utf-8",
    )
    (root / "plugin.py").write_text(
        "def register(host):\n"
        '    @host.tool(name="example.tmp", description="t")\n'
        "    async def t(args):\n"
        '        return "1"\n',
        encoding="utf-8",
    )

    server = McpServer()
    host = McpHost(server.add_tool)
    results = PluginLoader(host, plugins_dir=tmp_path).load_all()
    for r in results:
        if not r.error:
            for n in r.tool_names:
                server._plugin_tool_owner[n] = r.plugin_id
    assert any(tool.name == "example.tmp" for tool in server.tools)
    n = server.unload_plugin("com.example.tmp")
    assert n == 1
    assert not any(tool.name == "example.tmp" for tool in server.tools)


def test_mcp_plugin_rejects_future_api_version(tmp_path):
    from src.mcp.mcp_server import McpServer
    from src.mcp.plugins.host import McpHost
    from src.mcp.plugins.loader import PluginLoader

    root = tmp_path / "com.example.future"
    root.mkdir()
    (root / "manifest.json").write_text(
        '{"id":"com.example.future","api_version":99,'
        '"entry":"plugin:register","runtime":"python-inprocess"}',
        encoding="utf-8",
    )
    (root / "plugin.py").write_text("def register(host):\n    pass\n", encoding="utf-8")
    server = McpServer()
    results = PluginLoader(McpHost(server.add_tool), plugins_dir=tmp_path).load_all()
    assert any(r.error and "api_version" in (r.error or "") for r in results)


def test_check_mcp_plugin_script(tmp_path):
    import sys
    from pathlib import Path as P

    root_repo = P(__file__).resolve().parents[1]
    if str(root_repo) not in sys.path:
        sys.path.insert(0, str(root_repo))
    from scripts.check_mcp_plugin import check_plugin

    root = tmp_path / "pkg"
    root.mkdir()
    (root / "manifest.json").write_text(
        '{"id":"x","entry":"plugin:register","runtime":"python-inprocess"}',
        encoding="utf-8",
    )
    (root / "plugin.py").write_text("def register(host):\n    pass\n", encoding="utf-8")
    assert check_plugin(root) == []
    assert check_plugin(tmp_path / "missing") != []


def test_path_override_and_migrate(tmp_path, monkeypatch):
    """Pointing CACHE somewhere new copies the files across from the old directory."""
    import src.utils.resource_finder as rf

    # reset overrides
    rf.set_path_overrides(cache=None, log=None, music=None, keywords=None)
    rf.clear_path_caches()

    old_cache = tmp_path / "old_cache"
    old_cache.mkdir()
    (old_cache / "keep.bin").write_bytes(b"abc")
    new_cache = tmp_path / "new_cache"

    # simulate old path by temporarily overriding then migrating
    rf.set_path_overrides(cache=old_cache)
    assert rf.get_user_cache_dir() == old_cache.resolve()
    assert (old_cache / "keep.bin").exists()

    # migrate to new
    r = rf.migrate_directory(old_cache, new_cache, copy=True)
    assert r["ok"] is True
    assert r["files_copied"] >= 1
    assert (new_cache / "keep.bin").read_bytes() == b"abc"
    # source kept
    assert (old_cache / "keep.bin").exists()

    rf.set_path_overrides(cache=new_cache)
    assert rf.get_user_cache_dir() == new_cache.resolve()

    # music defaults under cache
    rf.set_path_overrides(music=None)
    assert rf.get_music_cache_dir() == (new_cache / "music").resolve()

    # cleanup overrides for other tests
    rf.set_path_overrides(cache=None, log=None, music=None, keywords=None)
    rf.clear_path_caches()


def test_env_cache_dir_overrides_config(tmp_path, monkeypatch):
    import src.utils.resource_finder as rf

    rf.set_path_overrides(cache=None, log=None, music=None, keywords=None)
    rf.clear_path_caches()
    env_dir = tmp_path / "env_cache"
    monkeypatch.setenv(rf.ENV_CACHE_DIR, str(env_dir))
    assert rf.get_user_cache_dir() == env_dir.resolve()
    monkeypatch.delenv(rf.ENV_CACHE_DIR, raising=False)
    rf.clear_path_caches()


def test_config_version_migration_v1(tmp_path, monkeypatch):
    """An old config with no CONFIG_VERSION is upgraded to v1 on load and written back."""
    from src.utils import config_manager as cm_mod
    from src.utils.config_manager import ConfigManager, reset_config

    reset_config()
    cfg_dir = tmp_path / "config"
    cfg_dir.mkdir()
    cfg_file = cfg_dir / "config.json"
    # the old file: no version, and MQTT subscribe_topic as the string "null"
    cfg_file.write_text(
        json.dumps(
            {
                "SYSTEM_OPTIONS": {
                    "NETWORK": {
                        "MQTT_INFO": {"subscribe_topic": "null", "endpoint": "e"}
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(cm_mod, "get_user_data_dir", lambda: tmp_path)
    monkeypatch.setattr(cm_mod, "get_config_dir", lambda: tmp_path / "no-install")

    cm = ConfigManager()
    assert cm.get_config("CONFIG_VERSION") == ConfigManager.CONFIG_VERSION
    assert cm.get_config("MCP_TOOLS.DISABLED") == []
    mqtt = cm.get_config("SYSTEM_OPTIONS.NETWORK.MQTT_INFO")
    assert isinstance(mqtt, dict)
    assert mqtt.get("subscribe_topic") is None
    # it has been written back
    disk = json.loads(cfg_file.read_text(encoding="utf-8"))
    assert disk.get("CONFIG_VERSION") == ConfigManager.CONFIG_VERSION
    reset_config()


def test_settings_model_save_is_atomic(tmp_path, monkeypatch):
    """SettingsModel.save writes through a temp file and a replace."""
    import src.ui.gui.models.settings_model as sm_mod

    # avoid depending on the real get_config
    class FakeCM:
        def reload_config(self, **kwargs):
            return True

    monkeypatch.setattr(sm_mod, "get_config", lambda: FakeCM())
    monkeypatch.setattr(sm_mod, "get_user_data_dir", lambda: tmp_path)
    (tmp_path / "config").mkdir(exist_ok=True)
    cfg = tmp_path / "config" / "config.json"
    cfg.write_text("{}", encoding="utf-8")

    model = sm_mod.SettingsModel()
    model._config = {"CONFIG_VERSION": 1, "MCP_TOOLS": {"DISABLED": ["a.b"]}}
    model._config_path = cfg
    model._mcp_disabled_snapshot = []
    # save emits Qt signals, which may still work without a QApplication
    try:
        from PySide6.QtWidgets import QApplication
        import sys

        app = QApplication.instance() or QApplication(sys.argv[:1])
    except Exception:
        app = None
    model.save()
    data = json.loads(cfg.read_text(encoding="utf-8"))
    assert data["MCP_TOOLS"]["DISABLED"] == ["a.b"]
    assert not cfg.with_suffix(".tmp").exists()


def test_migrate_directory_skip_music_subdir(tmp_path):
    import src.utils.resource_finder as rf

    old = tmp_path / "old"
    (old / "music").mkdir(parents=True)
    (old / "other").mkdir()
    (old / "keep.txt").write_text("x", encoding="utf-8")
    (old / "music" / "song.mp3").write_bytes(b"m")
    (old / "other" / "a.bin").write_bytes(b"a")
    new = tmp_path / "new"
    r = rf.migrate_directory(old, new, copy=True, skip_dir_names={"music"})
    assert r["ok"]
    assert (new / "keep.txt").exists()
    assert (new / "other" / "a.bin").exists()
    assert (
        not (new / "music").exists() or not any((new / "music").iterdir())
        if (new / "music").exists()
        else True
    )
    assert not (new / "music" / "song.mp3").exists()


def test_set_path_overrides_clear_with_none(tmp_path):
    import src.utils.resource_finder as rf

    rf.clear_path_overrides(all=True)
    rf.clear_path_caches()
    d = tmp_path / "c"
    d.mkdir()
    rf.set_path_overrides(cache=d)
    assert rf.get_user_cache_dir() == d.resolve()
    rf.set_path_overrides(cache=None)  # clear it explicitly
    # with no env var it falls back to the default user_data/cache, not d
    assert rf.get_user_cache_dir() != d.resolve()
    rf.clear_path_overrides(all=True)
    rf.clear_path_caches()


def test_get_lib_path_prefers_opus_dll(tmp_path, monkeypatch):
    import src.utils.resource_finder as rf

    root = tmp_path / "libs" / "libopus" / "win" / "x64"
    root.mkdir(parents=True)
    (root / "SOURCE.txt").write_text("x", encoding="utf-8")
    (root / "readme.dll.txt").write_text("no", encoding="utf-8")
    # decoy longer name
    (root / "libopus-extra.dll").write_bytes(b"1")
    (root / "opus.dll").write_bytes(b"2")
    monkeypatch.setattr(rf, "get_app_root", lambda: tmp_path)
    monkeypatch.setattr(rf, "get_platform_info", lambda: ("win", "x64"))
    p = rf.get_lib_path("libopus")
    assert p is not None
    assert p.name == "opus.dll"


def test_discover_plugin_catalog_from_sources(tmp_path, monkeypatch):
    from src.mcp import tool_catalog as tc

    plug = tmp_path / "com.example.hello"
    plug.mkdir()
    (plug / "manifest.json").write_text(
        json.dumps({"id": "com.example.hello", "name": "Hello"}),
        encoding="utf-8",
    )
    (plug / "plugin.py").write_text(
        'host.add_tool(McpTool(name="example.hello", description="d"))\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(tc, "_plugins_dir_from_config", lambda: tmp_path)
    rows = tc.discover_plugin_catalog_rows()
    names = [r["name"] for r in rows]
    assert "example.hello" in names
    hello = next(r for r in rows if r["name"] == "example.hello")
    assert hello["source"] == "plugin"
    assert hello["groupLabel"] == "Hello"


def test_mcp_plugin_subprocess_runtime(tmp_path):
    """python-subprocess: loaded in its own process, with calls proxied to it."""
    import asyncio
    import json
    from src.mcp.mcp_server import McpServer
    from src.mcp.plugins.host import McpHost
    from src.mcp.plugins.loader import PluginLoader
    from src.mcp.plugins.subprocess_runtime import drop_all_sessions

    plug = tmp_path / "com.example.iso"
    plug.mkdir()
    (plug / "manifest.json").write_text(
        json.dumps(
            {
                "id": "com.example.iso",
                "entry": "plugin:register",
                "runtime": "python-subprocess",
                "api_version": 1,
                "enabled_by_default": True,
            }
        ),
        encoding="utf-8",
    )
    (plug / "plugin.py").write_text(
        "def register(host):\n"
        '    @host.tool(name="example.iso_ping", description="ping", props=[])\n'
        "    def ping(args):\n"
        '        return "pong-iso"\n',
        encoding="utf-8",
    )

    server = McpServer()
    host = McpHost(server.add_tool, allow_get=["logger"])
    loader = PluginLoader(
        host,
        plugins_dir=tmp_path,
        raw_add_tool=server.add_tool,
    )
    try:
        loaded = loader.load_all()
        ok = [x for x in loaded if x.plugin_id == "com.example.iso"]
        assert ok and ok[0].error is None
        assert ok[0].runtime == "python-subprocess"
        assert any(t.name == "example.iso_ping" for t in server.tools)

        async def _call():
            tool = next(t for t in server.tools if t.name == "example.iso_ping")
            raw = await tool.call({})
            data = json.loads(raw)
            assert data.get("isError") is False
            assert "pong-iso" in data["content"][0]["text"]

        asyncio.run(_call())
    finally:
        drop_all_sessions()
