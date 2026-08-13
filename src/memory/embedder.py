"""Local text embeddings (BGE-small-en-v1.5, quantised ONNX).

Runs entirely on the machine - no API key, no network, nothing leaves the box.
onnxruntime + tokenizers only; sentence-transformers would drag in torch, which
is roughly 800MB and unshippable in an installer.

384 dimensions, ~34MB quantised. Vectors are mean-pooled over the attention mask
and L2-normalised, so cosine similarity is a plain dot product and sqlite-vec's
L2 distance is monotonic with it.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Optional, Sequence

import numpy as np

from src.logging import get_logger
from src.utils.resource_finder import get_app_root

logger = get_logger()

DIM = 384
_MAX_TOKENS = 256
# BGE is asymmetric: the query side takes an instruction prefix, stored
# documents do not. Skipping this measurably degrades ranking.
_QUERY_PREFIX = "Represent this sentence for searching relevant passages: "


class Embedder:
    """Lazily-loaded ONNX sentence embedder."""

    _instance: Optional["Embedder"] = None
    _lock = threading.Lock()

    def __init__(self, model_dir: Optional[Path] = None) -> None:
        self._dir = Path(model_dir) if model_dir else get_app_root() / "models" / "embedding"
        self._session = None
        self._tokenizer = None
        self._inputs: list[str] = []
        self._load_lock = threading.Lock()

    @classmethod
    def instance(cls) -> "Embedder":
        with cls._lock:
            if cls._instance is None:
                cls._instance = Embedder()
            return cls._instance

    @property
    def available(self) -> bool:
        return (self._dir / "model_quantized.onnx").exists() and (
            self._dir / "tokenizer.json"
        ).exists()

    def _ensure_loaded(self) -> None:
        if self._session is not None:
            return
        with self._load_lock:
            if self._session is not None:
                return
            import onnxruntime as ort
            from tokenizers import Tokenizer

            model = self._dir / "model_quantized.onnx"
            tok = self._dir / "tokenizer.json"
            if not model.exists() or not tok.exists():
                raise FileNotFoundError(
                    f"Embedding model missing under {self._dir}. Expected "
                    "model_quantized.onnx and tokenizer.json."
                )
            self._tokenizer = Tokenizer.from_file(str(tok))
            self._tokenizer.enable_truncation(max_length=_MAX_TOKENS)
            opts = ort.SessionOptions()
            # One thread: embedding is incidental work next to live audio.
            opts.intra_op_num_threads = 1
            opts.inter_op_num_threads = 1
            self._session = ort.InferenceSession(
                str(model), sess_options=opts, providers=["CPUExecutionProvider"]
            )
            self._inputs = [i.name for i in self._session.get_inputs()]
            logger.info(
                f"Embedder loaded ({DIM}d, inputs={self._inputs}) from {self._dir}"
            )

    def encode(self, texts: Sequence[str]) -> np.ndarray:
        """Return an (n, 384) float32 array of L2-normalised embeddings."""
        if isinstance(texts, str):
            texts = [texts]
        texts = [t if t and t.strip() else " " for t in texts]
        self._ensure_loaded()

        encodings = self._tokenizer.encode_batch(list(texts))
        maxlen = max(len(e.ids) for e in encodings)
        n = len(encodings)
        ids = np.zeros((n, maxlen), dtype=np.int64)
        mask = np.zeros((n, maxlen), dtype=np.int64)
        for i, e in enumerate(encodings):
            ln = len(e.ids)
            ids[i, :ln] = e.ids
            mask[i, :ln] = e.attention_mask

        feed = {}
        for name in self._inputs:
            if name == "input_ids":
                feed[name] = ids
            elif name == "attention_mask":
                feed[name] = mask
            elif name == "token_type_ids":
                feed[name] = np.zeros_like(ids)
        out = self._session.run(None, feed)[0]  # (n, seq, 384)

        # mean-pool over real tokens only
        m = mask.astype(np.float32)[..., None]
        summed = (out * m).sum(axis=1)
        counts = np.clip(m.sum(axis=1), 1e-9, None)
        vecs = summed / counts

        norms = np.linalg.norm(vecs, axis=1, keepdims=True)
        vecs = vecs / np.clip(norms, 1e-9, None)
        return vecs.astype(np.float32)

    def encode_one(self, text: str) -> np.ndarray:
        """Embed a document for storage."""
        return self.encode([text])[0]

    def encode_query(self, text: str) -> np.ndarray:
        """Embed a search query (adds the BGE instruction prefix)."""
        return self.encode([_QUERY_PREFIX + (text or "")])[0]


def get_embedder() -> Embedder:
    return Embedder.instance()
