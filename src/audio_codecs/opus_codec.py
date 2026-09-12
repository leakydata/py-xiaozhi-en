import numpy as np

# ============================================================
# load the Opus library (this must happen before opuslib is imported)
# ============================================================
from src.utils.opus_loader import setup_opus

setup_opus()

# must be imported after setup_opus()
import opuslib  # noqa: E402
import opuslib.api.decoder as decoder_api  # noqa: E402
import opuslib.api.encoder as encoder_api  # noqa: E402

from src.logging import get_logger  # noqa: E402

logger = get_logger()


_OPUS_BANDWIDTHS = {
    "NB": "8kHz", "MB": "12kHz", "WB": "16kHz",
    "SWB": "24kHz", "FB": "48kHz",
}


def parse_opus_toc(opus_data: bytes) -> dict:
    """Read the encoding parameters out of an Opus packet's TOC byte.

    Parsed per RFC 6716 section 3.1:
    - the top 5 bits are the config (giving the mode, bandwidth and single-frame length)
    - the bottom 2 bits are the code (giving the frame count)

    Returns:
        dict with keys: duration_ms, frame_ms, num_frames, bandwidth, mode
        None for an empty packet
    """
    if not opus_data:
        return None

    toc = opus_data[0]
    config = (toc >> 3) & 0x1F
    code = toc & 0x03

    # config -> mode + bandwidth + single-frame length
    if config < 12:
        mode = "SILK"
        bandwidth = ("NB", "MB", "WB")[config // 4]
        frame_ms = (10, 20, 40, 60)[config % 4]
    elif config < 16:
        mode = "Hybrid"
        bandwidth = ("SWB", "FB")[(config - 12) // 2]
        frame_ms = (10, 20)[config % 2]
    else:
        mode = "CELT"
        bandwidth = ("NB", "WB", "SWB", "FB")[(config - 16) // 4]
        frame_ms = (2.5, 5, 10, 20)[config % 4]

    # code -> frame count
    if code == 0:
        num_frames = 1
    elif code <= 2:
        num_frames = 2
    else:
        num_frames = (opus_data[1] & 0x3F) if len(opus_data) >= 2 else 1

    return {
        "duration_ms": frame_ms * num_frames,
        "frame_ms": frame_ms,
        "num_frames": num_frames,
        "bandwidth": bandwidth,
        "bandwidth_hz": _OPUS_BANDWIDTHS[bandwidth],
        "mode": mode,
    }


class OpusCodec:
    """Opus codec

    Uses libopus's encode_float and decode_float entry points,
    """

    def __init__(
        self,
        input_sample_rate: int,
        output_sample_rate: int,
        channels: int = 1,
    ):
        """Initialise the Opus codec

        Args:
            input_sample_rate: the input (encode) sample rate, e.g. 16000
            output_sample_rate: the output (decode) sample rate, e.g. 24000
            channels: the channel count, 1 by default
        """
        self.input_sample_rate = input_sample_rate
        self.output_sample_rate = output_sample_rate
        self.channels = channels
        self.encoder = None
        self.decoder = None

    def initialize(self):
        """Create the codec

        Raises:
            Exception: creation failed
        """
        try:
            # input encoder: 16kHz mono
            self.encoder = opuslib.Encoder(
                self.input_sample_rate,
                self.channels,
                opuslib.APPLICATION_VOIP,
            )

            # output decoder: 24kHz mono
            self.decoder = opuslib.Decoder(self.output_sample_rate, self.channels)

            logger.info(
                f"Opus codec created (float32 mode) | "
                f"encode: {self.input_sample_rate}Hz | "
                f"decode: {self.output_sample_rate}Hz"
            )
        except Exception as e:
            logger.error(f"failed to create the Opus codec: {e}", exc_info=True)
            raise

    def encode(self, pcm_float32: np.ndarray, frame_size: int) -> bytes:
        """Encode float32 PCM to Opus

        Args:
            pcm_float32: a float32 array in the range [-1.0, 1.0]
            frame_size: the sample count

        Returns:
            the Opus-encoded data

        Raises:
            RuntimeError: the encoder is not initialised
            Exception: encoding failed
        """
        if self.encoder is None:
            raise RuntimeError("the encoder is not initialised")

        # convert to bytes (float32 layout)
        pcm_bytes = pcm_float32.astype(np.float32).tobytes()

        # use encode_float (libopus supports it natively)
        return self.encoder.encode_float(pcm_bytes, frame_size)

    def decode(self, opus_data: bytes, frame_size: int) -> np.ndarray:
        """Decode Opus to float32 PCM

        Args:
            opus_data: the Opus-encoded data
            frame_size: the expected sample count

        Returns:
            a float32 array in the range [-1.0, 1.0]

        Raises:
            RuntimeError: the decoder is not initialised
            Exception: decoding failed
        """
        if self.decoder is None:
            raise RuntimeError("the decoder is not initialised")

        # use decode_float (libopus supports it natively)
        # note: channels was fixed when the Decoder was created, decode_float does not take it
        pcm_bytes = self.decoder.decode_float(opus_data, frame_size, decode_fec=False)

        # convert to a numpy array
        return np.frombuffer(pcm_bytes, dtype=np.float32)

    def close(self):
        """Release the resources, destroying the C-level codec state explicitly.

        opuslib's Encoder/Decoder.__del__ also calls destroy(), so encoder_state and
        decoder_state must be cleared first or the memory is freed twice.
        Idempotent: safe to call more than once.
        """
        if getattr(self, '_closed', False):
            return
        self._closed = True

        if self.encoder is not None:
            encoder_api.destroy(self.encoder.encoder_state)
            self.encoder.encoder_state = None  # stop __del__ freeing it a second time
            self.encoder = None
        if self.decoder is not None:
            decoder_api.destroy(self.decoder.decoder_state)
            self.decoder.decoder_state = None  # stop __del__ freeing it a second time
            self.decoder = None
        logger.debug("Opus codec released")
