# VoiceServe AI – Real-Time Voice Ordering Platform

- Built real-time AI voice call ordering system integrating Saaras v3 (STT), Kimi K2 (LLM), and Bulbul v3 (TTS) with custom agent architecture supporting dynamic tool execution for menu queries, cart management, validation, and personalized recommendations
- Achieved 83% latency reduction (12s→1.5s) by implementing Redis caching with intelligent preloading, stateful session memory, streamlined tool-calling workflows, and optimized STT audio processing with noise filtering and adaptive buffering
- Enhanced conversational accuracy through Pinecone vector search with semantic embeddings for fuzzy menu matching, interrupt-aware dialogue management with pause/resume capabilities, and multi-turn context retention for natural customer interactions
- Engineered scalable full-stack AI-powered POS system on FastAPI/React/PostgreSQL stack with FP-Growth-based smart recommendations, menu performance insights, and Gemini-driven multilingual reporting
