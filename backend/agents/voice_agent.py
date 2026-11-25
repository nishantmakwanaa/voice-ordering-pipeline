"""Main Voice Agent orchestrator: STT -> LLM (tool loop) -> TTS with interrupt handling."""

from __future__ import annotations

import asyncio
import base64
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Dict, List, Optional

import numpy as np
from sqlalchemy import select

from backend.agents.tools import (
    TOOL_DEFINITIONS,
    ensure_session_exists,
    execute_tool,
    normalize_uuid,
)
from backend.config import get_settings
from backend.database import get_db_session
from backend.models.database import Session
from backend.services.cache_service import cache_service
from backend.services.llm_service import llm_service
from backend.services.stt_service import AudioBuffer, apply_noise_filter, stt_service
from backend.services.tts_service import tts_service

logger = logging.getLogger(__name__)
settings = get_settings()

SendCallback = Callable[[Dict[str, Any]], Awaitable[None]]

MAX_TOOL_ITERATIONS = 5


@dataclass
class VoiceSessionState:
    """Per-session runtime state for audio buffering, dialogue, and interrupts."""

    session_id: str
    language: str = settings.saaras_language
    conversation_history: List[Dict[str, Any]] = field(default_factory=list)
    audio_buffer: AudioBuffer = field(default_factory=AudioBuffer)
    tts_task: Optional[asyncio.Task] = None
    processing_task: Optional[asyncio.Task] = None
    interrupted: bool = False
    is_speaking: bool = False
    resume_event: asyncio.Event = field(default_factory=asyncio.Event)

    def __post_init__(self) -> None:
        self.resume_event.set()


class VoiceAgent:
    """
    Orchestrates real-time voice ordering sessions:
    - Isolates AudioBuffer per session for concurrent calls
    - Runs STT -> LLM (with multi-step tool calling) -> streaming TTS
    - Supports pause, resume, and barge-in interruption
    - Syncs conversation state across Redis and PostgreSQL
    """

    def __init__(self) -> None:
        self._sessions: Dict[str, VoiceSessionState] = {}

    def _get_state(self, session_id: str) -> VoiceSessionState:
        sid = normalize_uuid(session_id)
        if sid not in self._sessions:
            self._sessions[sid] = VoiceSessionState(session_id=sid)
        return self._sessions[sid]

    async def start_session(
        self,
        session_id: str,
        language: str = settings.saaras_language,
    ) -> VoiceSessionState:
        """Initialize or restore a voice session from Redis / PostgreSQL."""
        sid = normalize_uuid(session_id)
        state = self._get_state(sid)
        state.language = language

        # Attempt Redis restore first for low latency
        cached = None
        if cache_service.is_connected:
            cached = await cache_service.get_session(sid)

        if cached:
            state.conversation_history = cached.get("conversation_history", [])
            state.language = cached.get("language", language)
            await cache_service.refresh_session_ttl(sid)
            return state

        # Fallback to PostgreSQL
        try:
            async with get_db_session() as db:
                session = await ensure_session_exists(db, sid, language=language)
                session.is_active = True
                state.conversation_history = list(session.conversation_history or [])
                state.language = session.language
        except Exception as exc:
            logger.warning("DB session restore skipped (%s): %s", sid, exc)

        await self._save_session_state(state, persist_db=False)
        return state

    async def end_session(self, session_id: str) -> None:
        """Cancel active tasks and persist final session state."""
        sid = normalize_uuid(session_id)
        state = self._sessions.pop(sid, None)
        if state is None:
            return

        await self._cancel_tts(state)
        if state.processing_task and not state.processing_task.done():
            state.processing_task.cancel()
            try:
                await state.processing_task
            except asyncio.CancelledError:
                pass

        await self._save_session_state(state, persist_db=True)

    async def handle_audio_chunk(
        self,
        session_id: str,
        base64_audio: str,
        send_cb: SendCallback,
    ) -> None:
        """Buffer incoming PCM16 audio, detect barge-in, and trigger STT when speech ends."""
        if not base64_audio:
            return

        state = self._get_state(session_id)
        try:
            pcm_bytes = base64.b64decode(base64_audio)
        except Exception as exc:
            logger.warning("Invalid base64 audio chunk: %s", exc)
            await send_cb({"type": "error", "message": "Invalid audio encoding."})
            return

        if not pcm_bytes:
            return

        # Barge-in detection: if user speaks above threshold while assistant is speaking
        if state.is_speaking and state.resume_event.is_set() and len(pcm_bytes) >= 2:
            usable = pcm_bytes[: len(pcm_bytes) - (len(pcm_bytes) % 2)]
            samples = np.frombuffer(usable, dtype=np.int16).astype(np.float32) / 32768.0
            energy = float(np.sqrt(np.mean(samples ** 2)))
            if energy > settings.saaras_noise_threshold * 1.5:
                logger.debug("Barge-in detected on session %s (energy=%.4f)", state.session_id, energy)
                await self.handle_interrupt(state.session_id, send_cb)

        filtered = apply_noise_filter(pcm_bytes, settings.saaras_noise_threshold)
        state.audio_buffer.add_chunk(filtered)

        # Auto-flush when speech is followed by sufficient silence
        if (
            state.audio_buffer.has_speech
            and state.audio_buffer.is_silent
            and state.audio_buffer.duration_seconds >= 0.3
        ):
            await self.handle_end_of_speech(state.session_id, send_cb)

    async def handle_end_of_speech(
        self,
        session_id: str,
        send_cb: SendCallback,
    ) -> None:
        """Flush buffered audio, transcribe via STT, and run LLM -> TTS pipeline."""
        state = self._get_state(session_id)
        if state.audio_buffer.duration_seconds < 0.1:
            state.audio_buffer.flush()
            return

        pcm_bytes = state.audio_buffer.flush()
        if not pcm_bytes:
            return

        transcript = await stt_service.transcribe_audio(pcm_bytes)
        if not transcript or not transcript.strip():
            return

        await send_cb({
            "type": "transcript",
            "text": transcript.strip(),
            "is_final": True,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

        await self._process_user_text(state, transcript.strip(), send_cb)

    async def handle_text_input(
        self,
        session_id: str,
        text: str,
        send_cb: SendCallback,
    ) -> None:
        """Process direct text input through the LLM -> TTS pipeline."""
        cleaned = (text or "").strip()
        if not cleaned:
            return

        state = self._get_state(session_id)
        await send_cb({
            "type": "transcript",
            "text": cleaned,
            "is_final": True,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        await self._process_user_text(state, cleaned, send_cb)

    async def handle_interrupt(
        self,
        session_id: str,
        send_cb: SendCallback,
    ) -> None:
        """Stop active TTS synthesis immediately (barge-in)."""
        state = self._get_state(session_id)
        state.interrupted = True
        state.resume_event.set()
        await self._cancel_tts(state)
        state.audio_buffer.flush()
        await send_cb({
            "type": "tts_audio",
            "data": "",
            "is_final": True,
            "message": "Playback interrupted",
        })

    async def handle_pause(
        self,
        session_id: str,
        send_cb: SendCallback,
    ) -> None:
        """Pause outgoing TTS audio streaming."""
        state = self._get_state(session_id)
        state.resume_event.clear()
        await send_cb({"type": "paused", "message": "Audio paused"})

    async def handle_resume(
        self,
        session_id: str,
        send_cb: SendCallback,
    ) -> None:
        """Resume paused TTS audio streaming."""
        state = self._get_state(session_id)
        state.resume_event.set()
        await send_cb({"type": "resumed", "message": "Audio resumed"})

    # ── Internal Pipeline Helpers ─────────────────────────────────────────────

    async def _process_user_text(
        self,
        state: VoiceSessionState,
        user_text: str,
        send_cb: SendCallback,
    ) -> None:
        """Run LLM with tool execution loop, persist session, and stream TTS."""
        await self._cancel_tts(state)
        state.interrupted = False
        state.resume_event.set()

        if not llm_service.is_connected:
            await llm_service.connect()

        response_text, updated_history, tool_calls = await llm_service.chat(
            user_message=user_text,
            conversation_history=state.conversation_history,
            tools=TOOL_DEFINITIONS,
        )

        # Tool execution loop
        iterations = 0
        while tool_calls and iterations < MAX_TOOL_ITERATIONS:
            iterations += 1
            tool_results = await self._execute_tool_calls(
                tool_calls=tool_calls,
                session_id=state.session_id,
                send_cb=send_cb,
            )
            response_text, updated_history, tool_calls = (
                await llm_service.continue_with_tool_results(
                    tool_results=tool_results,
                    conversation_history=updated_history,
                    tools=TOOL_DEFINITIONS,
                )
            )

        state.conversation_history = updated_history
        await self._save_session_state(state, persist_db=True)

        final_text = response_text or "I'm ready whenever you are!"
        await send_cb({
            "type": "llm_response",
            "text": final_text,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

        # Stream TTS in background task so WebSocket stays responsive for interrupts
        state.tts_task = asyncio.create_task(
            self._stream_tts(state, final_text, send_cb)
        )

    async def _execute_tool_calls(
        self,
        tool_calls: List[Dict[str, Any]],
        session_id: str,
        send_cb: SendCallback,
    ) -> List[Dict[str, Any]]:
        """Execute a batch of LLM tool calls and push live cart updates."""
        results: List[Dict[str, Any]] = []
        async with get_db_session() as db:
            for tc in tool_calls:
                name = tc["name"]
                args = tc.get("arguments") or {}
                output = await execute_tool(
                    tool_name=name,
                    arguments=args,
                    session_id=session_id,
                    db=db,
                )
                results.append({
                    "tool_call_id": tc["id"],
                    "name": name,
                    "content": output,
                })
                if isinstance(output, dict) and "cart" in output:
                    await send_cb({
                        "type": "cart_update",
                        "cart": output["cart"],
                    })
        return results

    async def _stream_tts(
        self,
        state: VoiceSessionState,
        text: str,
        send_cb: SendCallback,
    ) -> None:
        """Stream base64 TTS chunks while respecting pause/resume and interrupts."""
        state.is_speaking = True
        try:
            async for b64_chunk in tts_service.synthesize_base64_stream(text):
                await state.resume_event.wait()
                if state.interrupted:
                    break
                await send_cb({
                    "type": "tts_audio",
                    "data": b64_chunk,
                    "is_final": False,
                })
            if not state.interrupted:
                await send_cb({
                    "type": "tts_audio",
                    "data": "",
                    "is_final": True,
                })
        except asyncio.CancelledError:
            logger.debug("TTS stream cancelled for session %s", state.session_id)
        except Exception as exc:
            logger.error("TTS streaming error for session %s: %s", state.session_id, exc)
        finally:
            state.is_speaking = False

    async def _cancel_tts(self, state: VoiceSessionState) -> None:
        """Cancel and await any running TTS task."""
        if state.tts_task and not state.tts_task.done():
            state.tts_task.cancel()
            try:
                await state.tts_task
            except asyncio.CancelledError:
                pass
        state.tts_task = None
        state.is_speaking = False

    async def _save_session_state(
        self,
        state: VoiceSessionState,
        persist_db: bool = False,
    ) -> None:
        """Persist session conversation state to Redis and optionally PostgreSQL."""
        payload = {
            "session_id": state.session_id,
            "language": state.language,
            "conversation_history": state.conversation_history[-40:],
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        if cache_service.is_connected:
            await cache_service.set_session(state.session_id, payload)

        if persist_db:
            try:
                async with get_db_session() as db:
                    res = await db.execute(
                        select(Session).where(Session.id == state.session_id)
                    )
                    session = res.scalar_one_or_none()
                    if session:
                        session.conversation_history = state.conversation_history[-40:]
                        session.language = state.language
                        session.last_active_at = datetime.now(timezone.utc)
            except Exception as exc:
                logger.warning("Failed to persist session %s to DB: %s", state.session_id, exc)


# Global singleton
voice_agent = VoiceAgent()
