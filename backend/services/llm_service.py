"""Kimi K2 LLM service with tool calling and multi-turn context management."""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, List, Optional, Tuple

from openai import AsyncOpenAI
from openai.types.chat import ChatCompletion, ChatCompletionMessage

from backend.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

# System prompt for the voice ordering agent
SYSTEM_PROMPT = """You are VoiceServe, a friendly and efficient AI voice ordering assistant for a restaurant.

Your role:
- Help customers browse the menu and place orders via voice
- Ask clarifying questions when items are ambiguous
- Suggest relevant additions (drinks, sides, desserts)
- Confirm orders before checkout
- Keep responses SHORT and CONVERSATIONAL (1-3 sentences max) since they will be spoken aloud
- Never mention technical details like session IDs or API errors to customers

When using tools:
- Always use search_menu before recommending items you're not sure about
- After adding/removing cart items, briefly confirm the action
- Validate the order before checkout
- Use get_recommendations to suggest relevant add-ons

Language: Be warm, natural, and efficient. Avoid long lists unless asked."""


class LLMService:
    """
    Kimi K2 LLM integration via OpenAI-compatible API.

    Features:
    - Multi-turn conversation with rolling context window
    - Tool/function calling for menu operations
    - Streaming response support
    - Context compression when window exceeds limit
    """

    def __init__(self) -> None:
        self._client: Optional[AsyncOpenAI] = None

    async def connect(self) -> None:
        """Initialize the Kimi K2 client."""
        self._client = AsyncOpenAI(
            api_key=settings.kimi_api_key,
            base_url=settings.kimi_api_url,
        )
        logger.info("LLMService initialized (Kimi K2 @ %s)", settings.kimi_api_url)

    async def disconnect(self) -> None:
        """Close LLM client (no-op for OpenAI client)."""
        logger.info("LLMService disconnected.")

    @property
    def is_connected(self) -> bool:
        """Return True if the LLM client is initialized."""
        return self._client is not None

    @property
    def client(self) -> AsyncOpenAI:
        if self._client is None:
            raise RuntimeError("LLMService not connected.")
        return self._client

    @staticmethod
    def _parse_tool_arguments(raw_args: Optional[str]) -> Dict[str, Any]:
        """Safely parse JSON tool call arguments."""
        if not raw_args:
            return {}
        try:
            parsed = json.loads(raw_args)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            logger.warning("Failed to parse tool arguments: %r", raw_args)
            return {}

    async def _create_completion(
        self,
        messages: List[Dict],
        tools: Optional[List[Dict]] = None,
    ) -> ChatCompletion:
        """Call chat completions, passing tool params only when tools are provided."""
        kwargs: Dict[str, Any] = {
            "model": settings.kimi_model,
            "messages": messages,
            "max_tokens": settings.kimi_max_tokens,
            "temperature": settings.kimi_temperature,
        }
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"
        return await self.client.chat.completions.create(**kwargs)

    def _trim_context(self, messages: List[Dict]) -> List[Dict]:
        """
        Trim conversation history to fit within context window.
        Keeps system message and most recent exchanges.
        """
        # Rough token estimate: 4 chars ≈ 1 token
        total_chars = sum(len(json.dumps(m)) for m in messages)
        max_chars = settings.kimi_context_window * 3  # conservative estimate

        if total_chars <= max_chars:
            return messages

        # Keep system prompt + last N messages
        system_msgs = [m for m in messages if m.get("role") == "system"]
        other_msgs = [m for m in messages if m.get("role") != "system"]

        # Binary search for how many recent messages fit
        while other_msgs and total_chars > max_chars:
            other_msgs = other_msgs[2:]  # remove oldest user+assistant pair
            total_chars = sum(len(json.dumps(m)) for m in system_msgs + other_msgs)

        logger.debug("Trimmed context to %d messages", len(system_msgs) + len(other_msgs))
        return system_msgs + other_msgs

    async def chat(
        self,
        user_message: str,
        conversation_history: List[Dict],
        tools: Optional[List[Dict]] = None,
    ) -> Tuple[str, List[Dict], List[Dict]]:
        """
        Send a user message and get the assistant's response.

        Args:
            user_message: The user's input text.
            conversation_history: Prior conversation messages.
            tools: OpenAI-format tool definitions.

        Returns:
            Tuple of (response_text, updated_history, tool_calls_made)
        """
        messages = self._build_messages(user_message, conversation_history)
        messages = self._trim_context(messages)

        start = time.monotonic()
        tool_calls_made = []

        try:
            response = await self._create_completion(messages, tools=tools)
        except Exception as exc:
            logger.error("Kimi K2 API error: %s", exc)
            return "I'm sorry, I encountered an issue. Could you please repeat that?", conversation_history, []

        elapsed = time.monotonic() - start
        msg: ChatCompletionMessage = response.choices[0].message

        # Handle tool calls
        if msg.tool_calls:
            tool_calls_made = [
                {
                    "id": tc.id,
                    "name": tc.function.name,
                    "arguments": self._parse_tool_arguments(tc.function.arguments),
                }
                for tc in msg.tool_calls
            ]
            logger.debug("LLM requested %d tool call(s) in %.2fs", len(tool_calls_made), elapsed)

        response_text = msg.content or ""

        # Update history
        updated_history = list(conversation_history)
        updated_history.append({"role": "user", "content": user_message})
        updated_history.append({
            "role": "assistant",
            "content": response_text,
            **({"tool_calls": [
                {"id": tc.id, "type": "function", "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                for tc in msg.tool_calls
            ]} if msg.tool_calls else {}),
        })

        logger.debug("LLM response in %.2fs: %r", elapsed, response_text[:100])
        return response_text, updated_history, tool_calls_made

    async def continue_with_tool_results(
        self,
        tool_results: List[Dict],
        conversation_history: List[Dict],
        tools: Optional[List[Dict]] = None,
    ) -> Tuple[str, List[Dict], List[Dict]]:
        """
        Continue conversation after tool execution and also return any follow-up tool calls.

        Args:
            tool_results: Results from tool execution [{tool_call_id, name, content}].
            conversation_history: Current conversation history.
            tools: Tool definitions.

        Returns:
            Tuple of (response_text, updated_history, tool_calls_made)
        """
        updated_history = list(conversation_history)
        for result in tool_results:
            updated_history.append({
                "role": "tool",
                "tool_call_id": result["tool_call_id"],
                "name": result["name"],
                "content": json.dumps(result["content"], default=str),
            })

        messages = self._trim_context(
            [{"role": "system", "content": SYSTEM_PROMPT}] + updated_history
        )

        try:
            response = await self._create_completion(messages, tools=tools)
        except Exception as exc:
            logger.error("Kimi K2 tool result error: %s", exc)
            return "I've updated your order. Is there anything else?", updated_history, []

        msg = response.choices[0].message
        tool_calls_made: List[Dict] = []
        if msg.tool_calls:
            tool_calls_made = [
                {
                    "id": tc.id,
                    "name": tc.function.name,
                    "arguments": self._parse_tool_arguments(tc.function.arguments),
                }
                for tc in msg.tool_calls
            ]

        response_text = msg.content or (
            "" if tool_calls_made else "Done! Is there anything else I can help you with?"
        )

        updated_history.append({
            "role": "assistant",
            "content": response_text,
            **({"tool_calls": [
                {"id": tc.id, "type": "function", "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                for tc in msg.tool_calls
            ]} if msg.tool_calls else {}),
        })

        return response_text, updated_history, tool_calls_made

    async def chat_with_tool_results(
        self,
        tool_results: List[Dict],
        conversation_history: List[Dict],
        tools: Optional[List[Dict]] = None,
    ) -> Tuple[str, List[Dict]]:
        """
        Continue conversation after tool execution by sending tool results back.

        Args:
            tool_results: Results from tool execution [{tool_call_id, name, content}].
            conversation_history: Current conversation history.
            tools: Tool definitions.

        Returns:
            Tuple of (response_text, updated_history)
        """
        response_text, updated_history, _ = await self.continue_with_tool_results(
            tool_results=tool_results,
            conversation_history=conversation_history,
            tools=tools,
        )
        return response_text, updated_history

    def _build_messages(self, user_message: str, history: List[Dict]) -> List[Dict]:
        """Build the full messages list including system prompt."""
        return [{"role": "system", "content": SYSTEM_PROMPT}] + history + [
            {"role": "user", "content": user_message}
        ]


# Global singleton
llm_service = LLMService()
