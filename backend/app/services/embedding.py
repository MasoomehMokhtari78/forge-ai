"""
Embedding service abstraction and local Sentence Transformers implementation.
"""

from abc import ABC, abstractmethod
import asyncio
import hashlib
import logging
import math
from typing import ClassVar

import torch

from app.core.config import settings

logger = logging.getLogger(__name__)


class EmbeddingError(Exception):
    """User-safe exception raised when embedding generation fails."""
    pass


class EmbeddingService(ABC):
    """Abstract interface for text embedding providers."""

    @property
    @abstractmethod
    def dimension(self) -> int:
        """Return the vector dimension of the embedding model."""
        pass

    @abstractmethod
    async def get_embeddings(self, texts: list[str]) -> list[list[float]]:
        """Generate vector embeddings for a list of text strings."""
        pass


def resolve_embedding_device(device_setting: str) -> str:
    """Resolve the computing device based on the configuration string.

    Supports:
      - 'auto': chooses 'cuda' if available, otherwise 'cpu'
      - 'cpu': explicitly uses CPU
      - 'cuda': explicitly uses CUDA (raises RuntimeError if unavailable)

    Raises:
      RuntimeError if 'cuda' is explicitly requested but unavailable.
      ValueError if an invalid device name is supplied.
    """
    dev = device_setting.strip().lower()
    if dev == "auto":
        return "cuda" if torch.cuda.is_available() else "cpu"
    elif dev == "cpu":
        return "cpu"
    elif dev == "cuda":
        if not torch.cuda.is_available():
            raise RuntimeError("CUDA is explicitly configured (EMBEDDING_DEVICE=cuda) but is not available.")
        return "cuda"
    else:
        raise ValueError(f"Invalid EMBEDDING_DEVICE: '{device_setting}'. Must be 'auto', 'cuda', or 'cpu'.")


class LocalEmbeddingService(EmbeddingService):
    """Local Sentence Transformers embedding provider running on CPU or CUDA."""

    # Class-level cache to ensure the model is loaded once and reused across requests
    _cached_models: ClassVar[dict[tuple[str, str], object]] = {}

    def __init__(
        self,
        model_name: str | None = None,
        dimension: int | None = None,
        device: str | None = None,
        batch_size: int = 32,
    ) -> None:
        self._model_name = model_name or settings.embedding_model
        self._dimension = dimension or settings.embedding_dimension
        self._device_setting = device or settings.embedding_device
        self._batch_size = batch_size
        self._resolved_device = resolve_embedding_device(self._device_setting)

    @property
    def dimension(self) -> int:
        return self._dimension

    @property
    def device(self) -> str:
        return self._resolved_device

    def _get_model(self):
        """Retrieve or lazily initialize the SentenceTransformer model singleton."""
        cache_key = (self._model_name, self._resolved_device)
        if cache_key not in self._cached_models:
            logger.info(
                "Loading local embedding model '%s' onto device '%s'...",
                self._model_name,
                self._resolved_device,
            )
            try:
                from sentence_transformers import SentenceTransformer

                model = SentenceTransformer(self._model_name, device=self._resolved_device)
                actual_dim = getattr(model, "get_embedding_dimension", model.get_sentence_embedding_dimension)()

                if actual_dim != self._dimension:
                    raise EmbeddingError(
                        f"Configured dimension ({self._dimension}) does not match "
                        f"model '{self._model_name}' output dimension ({actual_dim})."
                    )
                self._cached_models[cache_key] = model
                logger.info("Successfully loaded embedding model '%s' (dim: %d)", self._model_name, actual_dim)
            except Exception as exc:
                logger.exception("Failed to load local embedding model '%s': %s", self._model_name, exc)
                raise EmbeddingError(f"Failed to load local embedding model: {exc}") from exc

        return self._cached_models[cache_key]

    def _encode_sync(self, texts: list[str]) -> list[list[float]]:
        """Run synchronous batch encoding on the selected compute device."""
        model = self._get_model()
        try:
            embeddings_array = model.encode(
                texts,
                batch_size=self._batch_size,
                normalize_embeddings=True,
                show_progress_bar=False,
                convert_to_numpy=True,
            )
            return embeddings_array.tolist()
        except Exception as exc:
            logger.exception("Inference error in local embedding model: %s", exc)
            raise EmbeddingError("Failed to generate local embeddings.") from exc

    async def get_embeddings(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []

        # Run CPU/GPU compute in a worker thread to keep the async event loop responsive
        return await asyncio.to_thread(self._encode_sync, texts)


class MockEmbeddingService(EmbeddingService):
    """Deterministic mock embedding provider for tests and offline development."""

    def __init__(self, dimension: int | None = None) -> None:
        self._dimension = dimension or settings.embedding_dimension

    @property
    def dimension(self) -> int:
        return self._dimension

    async def get_embeddings(self, texts: list[str]) -> list[list[float]]:
        """Generate deterministic normalized float vectors based on text content."""
        results: list[list[float]] = []
        for text in texts:
            hasher = hashlib.sha256(text.encode("utf-8"))
            seed_bytes = hasher.digest()

            vector: list[float] = []
            for i in range(self._dimension):
                byte_val = seed_bytes[i % len(seed_bytes)]
                val = ((byte_val + i) % 256) / 128.0 - 1.0
                vector.append(val)

            norm = math.sqrt(sum(x * x for x in vector)) or 1.0
            results.append([x / norm for x in vector])

        return results


def get_default_embedding_service() -> EmbeddingService:
    """Factory to create the active embedding service based on settings."""
    if settings.embedding_device.lower() == "mock":
        return MockEmbeddingService(dimension=settings.embedding_dimension)

    return LocalEmbeddingService(
        model_name=settings.embedding_model,
        dimension=settings.embedding_dimension,
        device=settings.embedding_device,
    )
