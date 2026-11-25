"""WebSocket endpoint for real-time voice ordering sessions."""

from __future__ import annotations

import json
import logging
from typing import Any, Dict

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from backend.agents.tools import build_cart_response, normalize_uuid
from backend.agents.voice_agent import voice_agent
from backend.database import get_db_session
from backend.models.schemas import WSMessage

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Voice WebSocket"])


@router.websocket("/ws/voice/{session_id}")
async def voice_websocket(websocket: WebSocket, session_id: str) -> None:
    """
    Real-time bidirectional voice streaming endpoint.

    Client messages:
    - {"type": "audio_chunk", "data": "<base64 PCM16>"}
    - {"type": "end_of_speech"}
    - {"type": "interrupt"}
    - {"type": "pause"}
    - {"type": "resume"}
    - {"type": "text_input", "text": "..."}
    - {"type": "ping"}
    """
    await websocket.accept()
    sid = normalize_uuid(session_id)
    logger.info("WebSocket connected for session %s (raw=%s)", sid, session_id)

    async def send_json(payload: Dict[str, Any]) -> None:
        try:
            await websocket.send_json(payload)
        except Exception as exc:
            logger.debug("WebSocket send failed for session %s: %s", sid, exc)

    await voice_agent.start_session(sid)

    # Send initial cart snapshot so UI stays synced immediately
    try:
        async with get_db_session() as db:
            cart = await build_cart_response(db, sid)
        await send_json({"type": "cart_update", "cart": cart})
    except Exception as exc:
        logger.warning("Failed to load initial cart for session %s: %s", sid, exc)

    try:
        while True:
            raw_message = await websocket.receive_text()
            try:
                data = json.loads(raw_message)
                msg = WSMessage(**data)
            except (json.JSONDecodeError, ValidationError) as exc:
                await send_json({"type": "error", "message": f"Invalid message format: {exc}"})
                continue

            if msg.type == "ping":
                await send_json({"type": "pong"})
            elif msg.type == "audio_chunk":
                if msg.data:
                    await voice_agent.handle_audio_chunk(sid, msg.data, send_json)
            elif msg.type == "end_of_speech":
                await voice_agent.handle_end_of_speech(sid, send_json)
            elif msg.type == "interrupt":
                await voice_agent.handle_interrupt(sid, send_json)
            elif msg.type == "pause":
                await voice_agent.handle_pause(sid, send_json)
            elif msg.type == "resume":
                await voice_agent.handle_resume(sid, send_json)
            elif msg.type == "text_input":
                text = msg.text or msg.data or ""
                await voice_agent.handle_text_input(sid, text, send_json)

    except WebSocketDisconnect:
        logger.info("WebSocket disconnected for session %s", sid)
    except Exception as exc:
        logger.exception("WebSocket error for session %s: %s", sid, exc)
        await send_json({"type": "error", "message": "Internal voice session error."})
    finally:
        await voice_agent.end_session(sid)
