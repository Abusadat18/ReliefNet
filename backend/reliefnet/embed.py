"""Text embeddings for the Dedupe agent's vector search.

fastembed runs a multilingual MiniLM model locally (ONNX, no GPU, handles
Hinglish). The hash embedder is a dependency-free fallback that still puts
texts with shared words and character n-grams close together."""
from __future__ import annotations

import asyncio
import hashlib
import logging
import re

import numpy as np

from .config import get_settings

log = logging.getLogger(__name__)

_model = None
_mode: str | None = None
_lock = asyncio.Lock()


def _hash_embed(text: str, dim: int) -> list[float]:
    v = np.zeros(dim, dtype=np.float32)
    t = re.sub(r"\s+", " ", text.lower()).strip()
    tokens = re.findall(r"[a-z0-9ऀ-ॿ]+", t)
    feats = list(tokens)
    for tok in tokens:
        padded = f"#{tok}#"
        feats += [padded[i : i + 3] for i in range(len(padded) - 2)]
    for f in feats:
        h = int.from_bytes(hashlib.blake2b(f.encode(), digest_size=8).digest(), "little")
        v[h % dim] += 1.0 if (h >> 63) & 1 else -1.0
    n = np.linalg.norm(v)
    return (v / n).tolist() if n else v.tolist()


def mode() -> str:
    global _mode
    if _mode is None:
        s = get_settings()
        _mode = s.embed_mode
        if _mode == "auto":
            try:
                import fastembed  # noqa: F401

                _mode = "fastembed"
            except ImportError:
                _mode = "hash"
    return _mode


def _load():
    global _model, _mode
    if _model is None:
        from fastembed import TextEmbedding

        try:
            _model = TextEmbedding(model_name=get_settings().embed_model)
        except Exception as e:  # offline or download failure
            log.warning("fastembed unavailable (%s); falling back to hash embeddings", e)
            _mode = "hash"
            return None
    return _model


async def embed(texts: list[str]) -> list[list[float]]:
    dim = get_settings().embed_dim
    if mode() == "fastembed":
        async with _lock:
            model = await asyncio.to_thread(_load)
            if model is not None:
                vecs = await asyncio.to_thread(lambda: list(model.embed(texts)))
                out = []
                for v in vecs:
                    a = np.asarray(v, dtype=np.float32)
                    n = np.linalg.norm(a)
                    out.append((a / n if n else a).tolist())
                return out
    return [_hash_embed(t, dim) for t in texts]


async def warmup() -> str:
    """Load the model before agents start, so a first-run download cannot stall lease renewals."""
    await embed(["warm up"])
    return mode()


async def embed_one(text: str) -> list[float]:
    return (await embed([text]))[0]
