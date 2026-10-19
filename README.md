# VoiceServe AI: Real-Time Voice Ordering Platform

Real-time AI voice call ordering system with tool execution for menu queries, cart management, validation, and recommendations.

## Highlights
- STT: Saaras v3, LLM: Kimi K2, TTS: Bulbul v3
- Response latency reduced from 12s to 1.5s using Redis caching with preloading, stateful session memory, and optimized STT audio processing
- Pinecone vector search for fuzzy menu matching, interrupt-aware dialogue, and multi-turn context
- Full-stack POS on FastAPI, React, PostgreSQL with FP-Growth recommendations and Gemini multilingual reporting
