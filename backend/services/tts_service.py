"""Bulbul v3 Text-to-Speech service with streaming audio synthesis."""

from __future__ import annotations

import asyncio
import base64
import logging
import time
from typing import AsyncGenerator, Optional

import httpx

from backend.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

CHUNK_SIZE = 4096  # bytes per streaming chunk


class TTSService:
    """
    Bulbul v3 TTS integration with streaming audio output.

    Features:
    - Streaming synthesis (low time-to-first-audio)
    - Interrupt-aware: synthesis can be cancelled mid-stream
    - Configurable voice, language, speed
    """

    def __init__(self) -> None:
        self._client: Optional[httpx.AsyncClient] = None

    async def connect(self) -> None:
        """Initialize HTTP client for Bulbul v3."""
        self._client = httpx.AsyncClient(
            base_url=settings.bulbul_api_url,
            headers={
                "Authorization": f"Bearer {settings.bulbul_api_key}",
                "Accept": "audio/pcm",
            },
            timeout=httpx.Timeout(60.0, connect=5.0),
        )
        logger.info("TTSService initialized (Bulbul v3 @ %s)", settings.bulbul_api_url)

    async def disconnect(self) -> None:
        """Close the HTTP client."""
        if self._client:
            await self._client.aclose()

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            raise RuntimeError("TTSService not connected.")
        return self._client

    async def synthesize(self, text: str) -> bytes:
        """
        Synthesize speech for the given text and return complete audio bytes.

        Args:
            text: Text to synthesize.

        Returns:
            Raw PCM audio bytes.
        """
        chunks = []
        async for chunk in self.synthesize_stream(text):
            chunks.append(chunk)
        return b"".join(chunks)

    async def synthesize_stream(self, text: str) -> AsyncGenerator[bytes, None]:
        """
        Stream synthesized speech chunks as they arrive from Bulbul v3.

        Args:
            text: Text to synthesize.

        Yields:
            Raw PCM audio byte chunks.
        """
        if not text.strip():
            return

        start = time.monotonic()
        first_chunk = True

        payload = {
            "text": text,
            "voice": settings.bulbul_voice,
            "language": settings.bulbul_language,
            "speed": settings.bulbul_speed,
            "format": settings.bulbul_format,
            "stream": True,
        }

        try:
            async with self.client.stream("POST", "/synthesize", json=payload) as response:
                response.raise_for_status()
                async for chunk in response.aiter_bytes(CHUNK_SIZE):
                    if chunk:
                        if first_chunk:
                            ttfa = time.monotonic() - start
                            logger.debug("TTS time-to-first-audio: %.3fs", ttfa)
                            first_chunk = False
                        yield chunk
                        await asyncio.sleep(0)  # allow event loop to process other tasks

        except httpx.HTTPStatusError as exc:
            logger.error(
                "Bulbul TTS API error %d: %s",
                exc.response.status_code,
                exc.response.text,
            )
        except httpx.RequestError as exc:
            logger.error("Bulbul TTS request error: %s", exc)

        total = time.monotonic() - start
        logger.debug("TTS synthesis complete in %.2fs for %d chars", total, len(text))

    async def synthesize_base64_stream(self, text: str) -> AsyncGenerator[str, None]:
        """
        Synthesize and yield base64-encoded audio chunks (for WebSocket transport).

        Args:
            text: Text to synthesize.

        Yields:
            Base64-encoded audio chunk strings.
        """
        async for chunk in self.synthesize_stream(text):
            yield base64.b64encode(chunk).decode("utf-8")


# Global singleton
tts_service = TTSService()
