"""Local, free text embeddings (fastembed runs on your CPU; nothing is sent anywhere).

An embedding is a list of numbers describing what a sentence *means*, so
"make a minecraft server" and "the last mc server died" come out close together.
If the model can't load, the bot still works and falls back to keyword matching.
"""
import asyncio
import logging
from pathlib import Path

import numpy as np

log = logging.getLogger("bot.memory")

MODEL_NAME = "BAAI/bge-small-en-v1.5"  # small (~70 MB), fast, good quality


class Embedder:
    def __init__(self, cache_dir: Path):
        self.cache_dir = cache_dir
        self._model = None
        self.available = False

    async def load(self) -> None:
        try:
            self._model = await asyncio.to_thread(self._load_model)
            self.available = True
            log.info("Local embeddings ready (%s)", MODEL_NAME)
        except Exception as e:
            log.warning("Local embeddings unavailable (%s); memory will use keyword matching", e.__class__.__name__)

    def _load_model(self):
        from fastembed import TextEmbedding  # imported here so a broken install can't stop the bot
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        return TextEmbedding(MODEL_NAME, cache_dir=str(self.cache_dir))

    async def embed(self, texts: list[str]) -> list[np.ndarray] | None:
        """Normalized vectors, or None if embeddings are off."""
        if not self.available or not texts:
            return None
        vectors = await asyncio.to_thread(lambda: [np.asarray(v, dtype=np.float32) for v in self._model.embed(texts)])
        return [v / (np.linalg.norm(v) or 1.0) for v in vectors]


def to_blob(v: np.ndarray | None) -> bytes | None:
    return None if v is None else v.astype(np.float16).tobytes()


def from_blob(b: bytes | None) -> np.ndarray | None:
    return None if not b else np.frombuffer(b, dtype=np.float16).astype(np.float32)
