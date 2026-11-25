"""Saaras v3 Speech-to-Text service with noise filtering and adaptive buffering."""

from __future__ import annotations

import asyncio
import base64
import logging
import time
from dataclasses import dataclass, field
from typing import AsyncGenerator, Callable, List, Optional

import httpx
import numpy as np

from backend.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


@dataclass
class AudioBuffer:
    """Adaptive audio buffer that accumulates chunks before sending."""

    sample_rate: int = settings.saaras_sample_rate
    chunk_duration_ms: int = 100          # process in 100ms windows
    silence_threshold: float = settings.saaras_noise_threshold
    _chunks: List[bytes] = field(default_factory=list)
    _silence_frames: int = 0
    _speech_started: bool = False
    _total_frames: int = 0

    def add_chunk(self, pcm_bytes: bytes) -> None:
        """Add a raw PCM audio chunk to the buffer."""
        if not pcm_bytes:
            return
        usable_len = len(pcm_bytes) - (len(pcm_bytes) % 2)
        if usable_len == 0:
            return
        pcm_bytes = pcm_bytes[:usable_len]

        self._chunks.append(pcm_bytes)
        self._total_frames += usable_len // 2  # 16-bit samples

        # Detect energy level
        samples = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32) / 32768.0
        energy = float(np.sqrt(np.mean(samples ** 2)))

        if energy > self.silence_threshold:
            self._speech_started = True
            self._silence_frames = 0
        elif self._speech_started:
            self._silence_frames += 1

    @property
    def has_speech(self) -> bool:
        return self._speech_started

    @property
    def is_silent(self) -> bool:
        """True if we've seen >500ms of silence after speech."""
        frames_for_500ms = int(self.sample_rate * 0.5)
        return self._silence_frames * (self.sample_rate * self.chunk_duration_ms // 1000) >= frames_for_500ms

    def flush(self) -> bytes:
        """Return all buffered audio and reset."""
        data = b"".join(self._chunks)
        self._chunks.clear()
        self._silence_frames = 0
        self._speech_started = False
        self._total_frames = 0
        return data

    @property
    def duration_seconds(self) -> float:
        """Duration of buffered audio in seconds."""
        return self._total_frames / max(self.sample_rate, 1)


def apply_noise_filter(pcm_bytes: bytes, threshold: float = 0.02) -> bytes:
    """
    Simple spectral noise gate: zero-out samples below energy threshold.

    Args:
        pcm_bytes: Raw 16-bit PCM audio bytes.
        threshold: RMS energy threshold (0–1 normalized).

    Returns:
        Filtered PCM bytes.
    """
    if not pcm_bytes or len(pcm_bytes) < 2:
        return b""
    usable_len = len(pcm_bytes) - (len(pcm_bytes) % 2)
    pcm_bytes = pcm_bytes[:usable_len]

    samples = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32)
    normalized = samples / 32768.0
    rms = float(np.sqrt(np.mean(normalized ** 2)))

    if rms < threshold:
        # Below threshold — treat as silence
        return b"\x00" * len(pcm_bytes)

    # Simple Wiener-style noise reduction: soft-threshold small values
    noise_floor = threshold * 32768.0
    filtered = np.where(np.abs(samples) < noise_floor, samples * 0.1, samples)
    return filtered.astype(np.int16).tobytes()


class STTService:
    """
    Saaras v3 Speech-to-Text integration.

    Supports:
    - Streaming audio transcription via HTTP POST
    - Noise filtering before upload
    - Adaptive buffering to batch small audio chunks
    - Interrupt-aware transcription (early flush)
    """

    def __init__(self) -> None:
        self._client: Optional[httpx.AsyncClient] = None
        self._buffer = AudioBuffer()

    async def connect(self) -> None:
        """Initialize the HTTP client."""
        self._client = httpx.AsyncClient(
            base_url=settings.saaras_api_url,
            headers={
                "Authorization": f"Bearer {settings.saaras_api_key}",
                "Content-Type": "application/octet-stream",
            },
            timeout=httpx.Timeout(30.0, connect=5.0),
        )
        logger.info("STTService initialized (Saaras v3 @ %s)", settings.saaras_api_url)

    async def disconnect(self) -> None:
        """Close HTTP client."""
        if self._client:
            await self._client.aclose()

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            raise RuntimeError("STTService not connected.")
        return self._client

    async def transcribe_chunk(self, pcm_bytes: bytes, is_final: bool = False) -> Optional[str]:
        """
        Feed an audio chunk to the buffer and transcribe when ready.

        Args:
            pcm_bytes: Raw 16-bit PCM audio at configured sample rate.
            is_final: If True, flush buffer immediately and transcribe.

        Returns:
            Transcript string if transcription was performed, else None.
        """
        filtered = apply_noise_filter(pcm_bytes, settings.saaras_noise_threshold)
        self._buffer.add_chunk(filtered)

        should_transcribe = is_final or (self._buffer.has_speech and self._buffer.is_silent)
        if not should_transcribe or self._buffer.duration_seconds < 0.3:
            return None

        audio_data = self._buffer.flush()
        return await self._call_saaras_api(audio_data)

    async def transcribe_audio(self, pcm_bytes: bytes) -> str:
        """
        Directly transcribe a complete audio buffer (no buffering).

        Args:
            pcm_bytes: Raw 16-bit PCM audio.

        Returns:
            Transcript string.
        """
        filtered = apply_noise_filter(pcm_bytes, settings.saaras_noise_threshold)
        return await self._call_saaras_api(filtered) or ""

    async def _call_saaras_api(self, pcm_bytes: bytes) -> Optional[str]:
        """
        Call the Saaras v3 transcription endpoint.

        Args:
            pcm_bytes: Audio to transcribe.

        Returns:
            Transcript text or None on failure.
        """
        if not pcm_bytes or len(pcm_bytes) < 320:
            return None

        start = time.monotonic()
        try:
            response = await self.client.post(
                "/transcribe",
                content=pcm_bytes,
                params={
                    "language": settings.saaras_language,
                    "sample_rate": settings.saaras_sample_rate,
                    "encoding": "LINEAR16",
                    "enable_punctuation": "true",
                    "enable_disfluency_filter": "true",
                },
            )
            response.raise_for_status()
            data = response.json()
            transcript = data.get("transcript", "").strip()
            elapsed = time.monotonic() - start
            logger.debug("STT transcription in %.2fs: %r", elapsed, transcript)
            return transcript or None

        except httpx.HTTPStatusError as exc:
            logger.error("Saaras API error %d: %s", exc.response.status_code, exc.response.text)
            return None
        except httpx.RequestError as exc:
            logger.error("Saaras request error: %s", exc)
            return None

    def flush_buffer(self) -> bytes:
        """Force flush the audio buffer (e.g., on interrupt)."""
        return self._buffer.flush()


# Global singleton
stt_service = STTService()
