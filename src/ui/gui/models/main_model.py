"""主窗口 ViewModel."""

from PySide6.QtCore import Property, QTimer, Signal

from src.audio_codecs import audio_levels
from src.ui.gui.models.base_model import BaseModel

# Avatar animation refresh. 30 Hz is smooth enough for lip-sync and costs far
# less than the audio callback rate (50-100 Hz) it samples from.
_LEVEL_POLL_MS = 33


class MainModel(BaseModel):
    """主窗口数据模型."""

    # 信号
    ttsTextChanged = Signal()
    musicLineChanged = Signal()
    emotionUrlChanged = Signal()
    statusTextChanged = Signal()
    connectedChanged = Signal()
    autoModeChanged = Signal()
    modeTextChanged = Signal()
    buttonTextChanged = Signal()
    audioLevelChanged = Signal()
    deviceStateChanged = Signal()
    emotionNameChanged = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._tts_text = ""
        self._music_line = ""
        self._emotion_url = ""
        self._status_text = ""
        self._connected = False
        self._auto_mode = False
        self._mode_text = "Manual Mode"
        self._button_text = "Hold to Talk"
        self._emotion_name = "neutral"
        self._device_state = "idle"
        self._audio_level = 0.0

        # Poll the audio meters instead of pushing them through the EventBus;
        # see src/audio_codecs/audio_levels.py for why.
        self._level_timer = QTimer(self)
        self._level_timer.setInterval(_LEVEL_POLL_MS)
        self._level_timer.timeout.connect(self._poll_audio_level)
        self._level_timer.start()

    def _poll_audio_level(self) -> None:
        """Drive the avatar from whichever side is currently making sound."""
        if self._device_state == "speaking":
            level = audio_levels.get_output_level()
        elif self._device_state == "listening":
            level = audio_levels.get_input_level()
        else:
            level = 0.0
        # Only notify on visible change; QML bindings are not free.
        if abs(level - self._audio_level) > 0.004:
            self._audio_level = level
            self.audioLevelChanged.emit()

    # ========== Properties ==========

    @Property(str, notify=ttsTextChanged)
    def ttsText(self) -> str:
        # 历史属性名还是 ttsText，实际是对话内容
        return self._tts_text

    @Property(str, notify=musicLineChanged)
    def musicLine(self) -> str:
        return self._music_line

    @Property(str, notify=emotionUrlChanged)
    def emotionUrl(self) -> str:
        return self._emotion_url

    @Property(str, notify=statusTextChanged)
    def statusText(self) -> str:
        return self._status_text

    @Property(bool, notify=connectedChanged)
    def connected(self) -> bool:
        return self._connected

    @Property(bool, notify=autoModeChanged)
    def autoMode(self) -> bool:
        return self._auto_mode

    @Property(str, notify=modeTextChanged)
    def modeText(self) -> str:
        return self._mode_text

    @Property(str, notify=buttonTextChanged)
    def buttonText(self) -> str:
        return self._button_text

    @Property(float, notify=audioLevelChanged)
    def audioLevel(self) -> float:
        """Live 0..1 audio amplitude, already smoothed for animation."""
        return self._audio_level

    @Property(str, notify=deviceStateChanged)
    def deviceState(self) -> str:
        """idle | listening | speaking — drives avatar pose."""
        return self._device_state

    @Property(str, notify=emotionNameChanged)
    def emotionName(self) -> str:
        """Raw emotion name from the server (happy, sad, thinking, ...)."""
        return self._emotion_name

    # ========== Setters ==========

    def set_device_state(self, state: str):
        if self._device_state != state:
            self._device_state = state
            self.deviceStateChanged.emit()

    def set_emotion_name(self, name: str):
        if self._emotion_name != name:
            self._emotion_name = name
            self.emotionNameChanged.emit()

    def set_chat_text(self, text: str):
        if self._tts_text != text:
            self._tts_text = text
            self.ttsTextChanged.emit()

    def set_music_line(self, text: str):
        if self._music_line != text:
            self._music_line = text
            self.musicLineChanged.emit()

    def set_emotion_url(self, url: str):
        if self._emotion_url != url:
            self._emotion_url = url
            self.emotionUrlChanged.emit()

    def set_status(self, status: str, connected: bool):
        status_changed = self._status_text != status
        connected_changed = self._connected != connected

        if status_changed:
            self._status_text = status
            self.statusTextChanged.emit()

        if connected_changed:
            self._connected = connected
            self.connectedChanged.emit()

    def set_auto_mode(self, auto: bool):
        # 默认按钮文案；对话进行中会再被 Session 改成「停止对话」
        if self._auto_mode != auto:
            self._auto_mode = auto
            self._mode_text = "Auto Mode" if auto else "Manual Mode"
            self._button_text = "Start Chat" if auto else "Hold to Talk"
            self.autoModeChanged.emit()
            self.modeTextChanged.emit()
            self.buttonTextChanged.emit()

    def set_button_text(self, text: str):
        if self._button_text != text:
            self._button_text = text
            self.buttonTextChanged.emit()
