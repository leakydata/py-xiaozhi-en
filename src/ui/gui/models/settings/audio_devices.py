"""Enumerating, choosing and testing the audio devices."""

from __future__ import annotations

import asyncio
import time

import numpy as np
import sounddevice as sd
from PySide6.QtCore import Slot

from src.logging import get_logger

logger = get_logger()


class SettingsAudioDevicesMixin:
    # ========== audio device settings ==========

    def _apply_device_lists(self, devices: dict) -> None:
        """Fill the input and output lists from the enumeration and tell QML."""
        self._input_devices = list(devices.get("input") or [])
        self._output_devices = list(devices.get("output") or [])
        self._audio_devices_loaded = True
        logger.debug(
            f"loaded {len(self._input_devices)} input devices, "
            f"{len(self._output_devices)} output devices"
        )
        self.devicesChanged.emit()

    def _load_audio_devices(self, force: bool = False):
        """Load the available audio devices (a plain enumeration; PortAudio is not reinitialised).

        Args:
            force: True re-enumerates regardless (used when the settings open)
        """
        if self._audio_devices_loaded and not force:
            return
        try:
            from src.utils.audio_utils import list_audio_devices

            devices = list_audio_devices(include_virtual=True)
            self._apply_device_lists(devices)
        except Exception as e:
            logger.error(f"failed to load the audio devices: {e}", exc_info=True)
            self._input_devices = []
            self._output_devices = []

    @Slot(result=list)
    def getInputDevices(self) -> list:
        """The input devices (enumerated on the first call)."""
        self._load_audio_devices()
        return [d["name"] for d in self._input_devices]

    @Slot(result=list)
    def getOutputDevices(self) -> list:
        """The output devices (enumerated on the first call)."""
        self._load_audio_devices()
        return [d["name"] for d in self._output_devices]

    @Slot()
    def refreshDevices(self):
        """Refresh the device list live: stop the streams, re-enumerate PortAudio, reopen them.

        For a Bluetooth device connected while running, AudioPlugin must stop the streams before ``refresh_portaudio_devices``.
        Without an EventBus this falls back to a plain local enumeration.
        """
        if getattr(self, "_audio_devices_refreshing", False):
            self.statusMessage.emit("Device refresh in progress...")
            return

        event_bus = getattr(self, "_event_bus", None)
        task_manager = getattr(self, "_task_manager", None)

        if event_bus is None or task_manager is None:
            logger.warning(
                "SettingsModel: no EventBus or TaskManager, falling back to a local device enumeration"
            )
            self._load_audio_devices(force=True)
            self.statusMessage.emit(
                "Device list refreshed (audio streams not coordinated; a Bluetooth device connected later may still be invisible)"
            )
            return

        self._audio_devices_refreshing = True
        self.statusMessage.emit(
            "Refreshing audio devices (microphone/playback will briefly stop)..."
        )

        async def _refresh():
            from src.core.event_bus import Events
            from src.utils.audio_utils import list_audio_devices

            # the Future is the payload: AudioPlugin's handler calls set_result with the device list
            # emit awaits every handler, so the future is usually done by the time it returns
            loop = asyncio.get_running_loop()
            fut: asyncio.Future = loop.create_future()
            await event_bus.emit(Events.AUDIO_DEVICES_REFRESH_REQUEST, fut)
            if fut.done():
                result = fut.result()
            else:
                logger.warning(
                    "AudioPlugin did not complete the device-refresh Future, falling back to a local enumeration"
                )
                result = list_audio_devices(include_virtual=True)
                if not fut.done():
                    fut.set_result(result)
            return result if isinstance(result, dict) else {"input": [], "output": []}

        def _on_task_done(task: asyncio.Task):
            def _apply():
                try:
                    if task.cancelled():
                        devices = {"input": [], "output": []}
                    else:
                        exc = task.exception()
                        if exc is not None:
                            logger.error(
                                f"the device refresh task raised: {exc}", exc_info=exc
                            )
                            devices = {"input": [], "output": []}
                        else:
                            devices = task.result()
                except Exception as e:
                    logger.error(
                        f"failed to read the refresh result: {e}", exc_info=True
                    )
                    devices = {"input": [], "output": []}
                try:
                    if not isinstance(devices, dict):
                        devices = {"input": [], "output": []}
                    self._apply_device_lists(devices)
                    n_in = len(self._input_devices)
                    n_out = len(self._output_devices)
                    self.statusMessage.emit(
                        f"Device list refreshed (input {n_in} / output {n_out})"
                    )
                finally:
                    self._audio_devices_refreshing = False

            self._schedule_ui(_apply)

        try:
            task = task_manager.spawn(_refresh(), name="ui:audio_devices_refresh")
            if task is None:
                self._audio_devices_refreshing = False
                self._load_audio_devices(force=True)
                self.statusMessage.emit("App is shutting down; enumerated locally")
                return
            task.add_done_callback(_on_task_done)
        except Exception as e:
            self._audio_devices_refreshing = False
            logger.error(f"could not schedule the device refresh: {e}", exc_info=True)
            self._load_audio_devices(force=True)
            self.statusMessage.emit(f"Device refresh failed; enumerated locally: {e}")

    def _schedule_ui(self, fn) -> None:
        """Hand the callback back to the Qt main thread (a spawn's done callback may run on the loop thread)."""
        try:
            from PySide6.QtCore import QTimer

            QTimer.singleShot(0, fn)
        except Exception:
            try:
                fn()
            except Exception as e:
                logger.error(f"the UI callback failed: {e}", exc_info=True)

    def _get_selectedInputIndex(self) -> int:
        """The index of the currently selected input device."""
        current_id = self._get_value("AUDIO_DEVICES.input_device_id", -1)
        current_name = self._get_value("AUDIO_DEVICES.input_device_name", "")

        # match on the device name first
        if current_name:
            for i, d in enumerate(self._input_devices):
                if d["raw_name"] == current_name:
                    return i

        # then on the device ID
        for i, d in enumerate(self._input_devices):
            if d["index"] == current_id:
                return i
        return 0

    def _set_selectedInputIndex(self, index: int):
        """Select an input device."""
        if 0 <= index < len(self._input_devices):
            device = self._input_devices[index]
            self._set_value("AUDIO_DEVICES.input_device_id", device["index"])
            self._set_value("AUDIO_DEVICES.input_device_name", device["raw_name"])
            self._set_value("AUDIO_DEVICES.input_sample_rate", device["sample_rate"])
            self._set_value("AUDIO_DEVICES.input_channels", min(device["channels"], 1))
            logger.info(f"input device selected: {device['name']}")

    def _get_selectedOutputIndex(self) -> int:
        """The index of the currently selected output device."""
        current_id = self._get_value("AUDIO_DEVICES.output_device_id", -1)
        current_name = self._get_value("AUDIO_DEVICES.output_device_name", "")

        # match on the device name first
        if current_name:
            for i, d in enumerate(self._output_devices):
                if d["raw_name"] == current_name:
                    return i

        # then on the device ID
        for i, d in enumerate(self._output_devices):
            if d["index"] == current_id:
                return i
        return 0

    def _set_selectedOutputIndex(self, index: int):
        """Select an output device."""
        if 0 <= index < len(self._output_devices):
            device = self._output_devices[index]
            self._set_value("AUDIO_DEVICES.output_device_id", device["index"])
            self._set_value("AUDIO_DEVICES.output_device_name", device["raw_name"])
            self._set_value("AUDIO_DEVICES.output_sample_rate", device["sample_rate"])
            self._set_value("AUDIO_DEVICES.output_channels", min(device["channels"], 2))
            logger.info(f"output device selected: {device['name']}")

    # device information display
    def _get_inputDeviceInfo(self) -> str:
        idx = self._get_selectedInputIndex()
        if 0 <= idx < len(self._input_devices):
            d = self._input_devices[idx]
            return f"Sample rate: {d['sample_rate']}Hz, channels: {d['channels']}"
        return "No device selected"

    def _get_outputDeviceInfo(self) -> str:
        idx = self._get_selectedOutputIndex()
        if 0 <= idx < len(self._output_devices):
            d = self._output_devices[idx]
            return f"Sample rate: {d['sample_rate']}Hz, channels: {d['channels']}"
        return "No device selected"

    # the Opus output sample rate
    def _get_opusOutputSampleRate(self) -> int:
        return self._get_value("AUDIO_DEVICES.opus_output_sample_rate", 24000)

    def _set_opusOutputSampleRate(self, value: int):
        self._set_value("AUDIO_DEVICES.opus_output_sample_rate", value)

    # the audio frame length
    def _get_frameDuration(self) -> int:
        return self._get_value("AUDIO_DEVICES.frame_duration", 20)

    def _set_frameDuration(self, value: int):
        if value in [20, 40, 60]:
            self._set_value("AUDIO_DEVICES.frame_duration", value)

    # audio tests
    @Slot()
    def testInputDevice(self):
        """Test the input device by recording."""
        if self._testing_input:
            return

        idx = self._get_selectedInputIndex()
        if idx < 0 or idx >= len(self._input_devices):
            self.statusMessage.emit("Select an input device first")
            return

        device = self._input_devices[idx]
        self._testing_input = True
        self.statusMessage.emit("Starting recording test...")

        self._run_worker(
            self._do_input_test,
            device,
            name="settings:input_test",
            test_kind="input",
            clear_flags=lambda: setattr(self, "_testing_input", False),
        )

    def _do_input_test(self, device: dict):
        """Run the recording test (_run_worker catches any exception)."""
        device_id = device["index"]
        sample_rate = device["sample_rate"]
        duration = 3

        self.statusMessage.emit(f"Speak into the microphone ({duration}s)...")
        time.sleep(1)

        recording = sd.rec(
            int(duration * sample_rate),
            samplerate=sample_rate,
            channels=1,
            device=device_id,
            dtype=np.float32,
        )
        sd.wait()

        max_amplitude = np.max(np.abs(recording))

        if max_amplitude < 0.001:
            self.statusMessage.emit("[FAIL] No audio signal detected")
            self.testComplete.emit("input", False)
        elif max_amplitude > 0.8:
            self.statusMessage.emit("[WARN] Audio signal clipping")
            self.testComplete.emit("input", True)
        else:
            self.statusMessage.emit(
                f"[OK] Recording test passed (level: {max_amplitude:.1%})"
            )
            self.testComplete.emit("input", True)

    @Slot()
    def testOutputDevice(self):
        """Test the output device by playing something."""
        if self._testing_output:
            return

        idx = self._get_selectedOutputIndex()
        if idx < 0 or idx >= len(self._output_devices):
            self.statusMessage.emit("Select an output device first")
            return

        device = self._output_devices[idx]
        self._testing_output = True
        self.statusMessage.emit("Starting playback test...")

        self._run_worker(
            self._do_output_test,
            device,
            name="settings:output_test",
            test_kind="output",
            clear_flags=lambda: setattr(self, "_testing_output", False),
        )

    def _do_output_test(self, device: dict):
        """Run the playback test (_run_worker catches any exception)."""
        device_id = device["index"]
        sample_rate = device["sample_rate"]
        duration = 2.0
        frequency = 440

        self.statusMessage.emit("Playing 440Hz test tone...")
        time.sleep(0.5)

        t = np.linspace(0, duration, int(sample_rate * duration))
        audio = 0.3 * np.sin(2 * np.pi * frequency * t)

        fade_samples = int(0.1 * sample_rate)
        audio[:fade_samples] *= np.linspace(0, 1, fade_samples)
        audio[-fade_samples:] *= np.linspace(1, 0, fade_samples)

        sd.play(audio, samplerate=sample_rate, device=device_id)
        sd.wait()

        self.statusMessage.emit("[OK] Playback test complete")
        self.testComplete.emit("output", True)
