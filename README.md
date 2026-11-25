# VoiceServe AI — Real-Time Voice Ordering Pipeline

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-Async%20WS%2BREST-009688.svg)](https://fastapi.tiangolo.com/)
[![React](https://img.shields.io/badge/React-18%20%2B%20Vite-61DAFB.svg)](https://react.dev/)
[![Docker](https://img.shields.io/badge/Docker-Compose-2496ED.svg)](docker-compose.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

> **Target latency profile:** 83% reduction (12s → 1.5s) via Redis caching & adaptive buffering | Real-time STT → LLM → TTS voice agent | Full-stack AI POS & ordering platform

---

## Proof & Reference Links (Models, Docs, Services & Code)

| Category | Resource | Link |
| :--- | :--- | :--- |
| **STT Model** | Sarvam AI **Saaras v3** Speech-to-Text | [Sarvam STT Docs](https://docs.sarvam.ai/api-reference/endpoints/speech-to-text) · [`stt_service.py`](backend/services/stt_service.py) |
| **LLM Model** | Moonshot AI **Kimi K2** (`kimi-k2-instruct`) | [Moonshot Platform](https://platform.kimi.ai) · [HF Model Card](https://huggingface.co/moonshotai/Kimi-K2-Instruct) · [`llm_service.py`](backend/services/llm_service.py) |
| **TTS Model** | Sarvam AI **Bulbul v3** Text-to-Speech | [Sarvam TTS Docs](https://docs.sarvam.ai/api-reference/endpoints/text-to-speech) · [`tts_service.py`](backend/services/tts_service.py) |
| **Vector DB & Embeddings** | **Pinecone** + `text-embedding-3-small` (`1536`-dim) | [Pinecone Docs](https://docs.pinecone.io/) · [Embeddings Guide](https://platform.openai.com/docs/guides/embeddings) · [`vector_service.py`](backend/services/vector_service.py) |
| **Recommendation Engine** | **FP-Growth** Association Rules (`mlxtend`) | [mlxtend FP-Growth Guide](https://rasbt.github.io/mlxtend/user_guide/frequent_patterns/fpgrowth/) · [`recommendation_service.py`](backend/services/recommendation_service.py) |
| **Reporting LLM** | Google **Gemini 1.5 Pro** (`gemini-1.5-pro`) | [Gemini API Docs](https://ai.google.dev/gemini-api/docs) · [`reports.py`](backend/routers/reports.py) |
| **Agent Orchestrator** | Multi-turn STT → LLM (tool loop) → TTS + Barge-in | [`voice_agent.py`](backend/agents/voice_agent.py) · [`tools.py`](backend/agents/tools.py) |
| **Backend & Cache Stack** | FastAPI + Async SQLAlchemy (PostgreSQL 15) + Redis 7 | [FastAPI](https://fastapi.tiangolo.com/) · [PostgreSQL](https://www.postgresql.org/docs/) · [Redis](https://redis.io/docs/) · [`main.py`](backend/main.py) |
| **Database Schema & Seed** | DDL migration + 15 menu items & 20 historical baskets | [`001_initial.sql`](migrations/001_initial.sql) · [`seed_menu.py`](scripts/seed_menu.py) |
| **Real-Time Voice UI** | React 18 WebSocket PCM-16 streamer & waveform | [`useVoiceSocket.js`](frontend/src/hooks/useVoiceSocket.js) · [`VoiceInterface.jsx`](frontend/src/components/VoiceInterface.jsx) |

---

## System Architecture

```text
┌──────────────────────────────────────────────────────────────────────────────┐
│                              VoiceServe AI                                   │
│                                                                              │
│  ┌────────────────────┐   WS /ws/voice/{id}   ┌───────────────────────────┐  │
│  │  React 18 + Vite   │◄─────────────────────►│      FastAPI Backend      │  │
│  │                    │                       │                           │  │
│  │  • VoiceInterface  │   REST (/menu, /cart, │  ┌─────────────────────┐  │  │
│  │  • MenuDisplay     │    /orders, /reports) │  │     VoiceAgent      │  │  │
│  │  • CartDisplay     │◄─────────────────────►│  │  Saaras v3 (STT)    │  │  │
│  │  • OrderHistory    │                       │  │    ▼                │  │  │
│  └────────────────────┘                       │  │  Kimi K2 (LLM+Tools)│  │  │
│                                               │  │    ▼                │  │  │
│                                               │  │  Bulbul v3 (TTS)    │  │  │
│                                               │  └──────────┬──────────┘  │  │
│                                               │             │             │  │
│                                               │  ┌──────────▼──────────┐  │  │
│                                               │  │ Redis 7 | Pinecone  │  │  │
│                                               │  │ PgSQL 15| FP-Growth │  │  │
│                                               │  └─────────────────────┘  │  │
│                                               └───────────────────────────┘  │
└──────────────────────────────────────────────────────────────────────────────┘
```

### How Each Model & Component Works Together

1. **Streaming Audio & Noise Gate ([`useVoiceSocket.js`](frontend/src/hooks/useVoiceSocket.js), [`stt_service.py`](backend/services/stt_service.py)):**
   - The browser captures `16 kHz` PCM-16 audio and streams chunks over `/ws/voice/{session_id}`.
   - `AudioBuffer` applies RMS energy gating (`saaras_noise_threshold=0.02`) and adaptive silence detection before sending complete speech segments to **Saaras v3 STT**.
2. **Transformer LLM Agent & Dynamic Tool Execution ([`llm_service.py`](backend/services/llm_service.py), [`voice_agent.py`](backend/agents/voice_agent.py), [`tools.py`](backend/agents/tools.py)):**
   - **Kimi K2** (`kimi-k2-instruct`, `32,768` context window, `temperature=0.3`) maintains multi-turn dialogue state in **Redis** (`TTL 1800s`) and **PostgreSQL**.
   - Executes structured OpenAI-format tools inside an iterative agent loop: `search_menu`, `add_to_cart`, `remove_from_cart`, `get_cart`, `validate_order`, `checkout`, and `get_recommendations`.
3. **Semantic Embedding Retrieval ([`vector_service.py`](backend/services/vector_service.py)):**
   - Generates `1536`-dim dense embeddings (`text-embedding-3-small`) for menu descriptions/tags and queries **Pinecone** (cosine similarity) for fuzzy natural-language dish matching (with SQL `ILIKE` keyword fallback when Pinecone is unconfigured).
4. **Association-Rule Recommendations ([`recommendation_service.py`](backend/services/recommendation_service.py)):**
   - Trains **FP-Growth** (`mlxtend.frequent_patterns.fpgrowth`, `min_support=0.05`, `min_confidence=0.3`) on historical completed order baskets at startup to suggest frequently co-ordered pairings (cached in Redis `TTL 900s`).
5. **Streaming Speech Synthesis & Barge-In ([`tts_service.py`](backend/services/tts_service.py)):**
   - **Bulbul v3** streams synthesized `pcm_16000` audio chunks back over WebSocket; client `interrupt`, `pause`, and `resume` frames halt or resume playback immediately.
6. **Multilingual POS Analytics ([`reports.py`](backend/routers/reports.py)):**
   - Aggregates live PostgreSQL sales/item metrics and uses **Gemini 1.5 Pro** (`gemini-1.5-pro`) to synthesize multilingual executive reports (with a deterministic summary fallback when `GEMINI_API_KEY` is absent).

---

## Data Sources, Schema & Seeding

This system operates on transactional restaurant POS data persisted in **PostgreSQL 15**, cached in **Redis 7**, and indexed in **Pinecone**:

- **Relational Schema ([`migrations/001_initial.sql`](migrations/001_initial.sql), [`backend/models/database.py`](backend/models/database.py)):**
  - `menu_items`, `voice_sessions`, `cart_items`, `orders`, and `order_items`.
- **Included Seed Dataset ([`scripts/seed_menu.py`](scripts/seed_menu.py)):**
  - Seeds **15 restaurant menu items** (with prices, calories, tags, allergens, prep times) and **20 historical multi-item order baskets** so FP-Growth rule mining and Pinecone indexing work immediately after setup.

---

## Design Benchmark Targets

Project performance targets from the system design specification (requires live API keys for Saaras v3, Kimi K2, Bulbul v3, Pinecone, and Gemini to benchmark end-to-end):

| Metric | Baseline | Target | Improvement |
| :--- | :---: | :---: | :---: |
| Average Response Latency | 12s | 1.5s | **83% ↓** |
| Menu Query Cache Hit Rate | — | 94% | — |
| Order Accuracy | 71% | 96% | **35% ↑** |
| Concurrent Sessions | 5 | 150+ | **30x ↑** |

---

## Repository Structure

```text
voice-ordering-pipeline/
├── backend/
│   ├── agents/
│   │   ├── __init__.py
│   │   ├── voice_agent.py      # STT → LLM (tool loop) → TTS orchestrator
│   │   └── tools.py            # Menu, cart, validation, checkout & recommender tools
│   ├── models/
│   │   ├── __init__.py
│   │   ├── database.py         # SQLAlchemy ORM models
│   │   └── schemas.py          # Pydantic request/response/WS schemas
│   ├── routers/
│   │   ├── __init__.py
│   │   ├── menu.py             # Menu CRUD & semantic search endpoints
│   │   ├── orders.py           # Order & cart management + recommendations
│   │   ├── voice.py            # WebSocket /ws/voice/{session_id}
│   │   └── reports.py          # Sales analytics & Gemini multilingual reporting
│   ├── services/
│   │   ├── __init__.py
│   │   ├── stt_service.py      # Saaras v3 STT + noise filter + AudioBuffer
│   │   ├── llm_service.py      # Kimi K2 LLM client + tool calling
│   │   ├── tts_service.py      # Bulbul v3 streaming TTS client
│   │   ├── cache_service.py    # Redis caching & preloading
│   │   ├── vector_service.py   # Pinecone semantic menu search
│   │   └── recommendation_service.py  # mlxtend FP-Growth recommender
│   ├── __init__.py
│   ├── config.py               # Pydantic settings (.env)
│   ├── database.py             # Async PostgreSQL engine & sessions
│   └── main.py                 # FastAPI app & lifespan initialization
├── frontend/
│   ├── src/
│   │   ├── components/
│   │   │   ├── VoiceInterface.jsx
│   │   │   ├── MenuDisplay.jsx
│   │   │   ├── CartDisplay.jsx
│   │   │   └── OrderHistory.jsx
│   │   ├── hooks/
│   │   │   └── useVoiceSocket.js
│   │   ├── App.css
│   │   ├── App.jsx
│   │   └── main.jsx
│   ├── Dockerfile
│   ├── index.html
│   ├── nginx.conf
│   ├── package.json
│   └── vite.config.js
├── migrations/
│   └── 001_initial.sql         # Initial PostgreSQL schema
├── scripts/
│   └── seed_menu.py            # Seeds 15 menu items + 20 historical baskets
├── docker-compose.yml
├── Dockerfile.backend
├── .env.example
├── .gitignore
├── requirements.txt
├── LICENSE
└── README.md
```

---

## Quick Start

### Docker Compose (Recommended)

```bash
# 1. Clone the repository
git clone https://github.com/nishantmakwanaa/voice-ordering-pipeline.git
cd voice-ordering-pipeline

# 2. Configure environment variables
cp .env.example .env
# Edit .env with your API keys (SAARAS_API_KEY, KIMI_API_KEY, BULBUL_API_KEY, PINECONE_API_KEY, GEMINI_API_KEY)

# 3. Start PostgreSQL, Redis, FastAPI backend, and React frontend
docker compose up --build

# 4. Seed the menu & historical order baskets
docker compose exec backend python scripts/seed_menu.py

# Frontend: http://localhost:3000 | API Docs: http://localhost:8000/docs
```

### Manual Setup

```bash
# Backend (Python 3.11+, PostgreSQL 15+, Redis 7+)
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
psql -U voiceserve -d voiceserve -f migrations/001_initial.sql
python scripts/seed_menu.py
uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload

# Frontend (Node.js 18+)
cd frontend && npm install && npm run dev
```

---

## API & WebSocket Reference

Interactive Swagger docs: `http://localhost:8000/docs`.

| Method | Path | Description |
| :--- | :--- | :--- |
| `GET` | `/health` | Service health check |
| `WS` | `/ws/voice/{session_id}` | Real-time voice streaming WebSocket |
| `GET` / `POST` | `/menu`, `/menu/{item_id}` | Menu listing & admin CRUD |
| `GET` | `/menu/search` | Semantic (Pinecone) / keyword menu search |
| `GET` / `POST` / `PUT` | `/orders`, `/orders/{order_id}`, `/orders/{order_id}/status` | Order management |
| `GET` / `POST` / `DELETE` | `/cart/{session_id}`, `/cart/{session_id}/add`, `/cart/{session_id}/checkout` | Session cart & checkout |
| `GET` | `/recommendations/{session_id}` | FP-Growth smart item suggestions |
| `GET` / `POST` | `/reports/menu-performance`, `/reports/sales-summary`, `/reports/generate` | Sales metrics & Gemini AI report |

---

## License

MIT License — see [LICENSE](LICENSE) for details.
