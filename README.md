# VoiceServe AI — Real-Time Voice Ordering Pipeline

> **Target latency profile:** 83% reduction (12s → 1.5s) via Redis caching & adaptive buffering | Real-time STT → LLM → TTS pipeline | Full-stack AI POS & Voice Ordering

---

## Architecture

```text
┌──────────────────────────────────────────────────────────────────────────────┐
│                              VoiceServe AI                                   │
│                                                                              │
│  ┌────────────────────┐   WS /ws/voice/{id}   ┌───────────────────────────┐  │
│  │  React 18 + Vite   │◄─────────────────────►│      FastAPI Backend      │  │
│  │                    │                       │                           │  │
│  │  • VoiceInterface  │   REST (/menu, /cart, │  ┌─────────────────────┐  │  │
│  │  • MenuDisplay     │    /orders, /reports) │  │  VoiceAgent         │  │  │
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

### End-to-End Request Flow
1. **Audio Capture & Streaming:** The React hook [`useVoiceSocket.js`](frontend/src/hooks/useVoiceSocket.js) streams 16 kHz PCM-16 audio chunks over WebSocket (`/ws/voice/{session_id}`).
2. **STT & Adaptive Buffering ([`stt_service.py`](backend/services/stt_service.py)):** `AudioBuffer` applies RMS-based noise gating (`saaras_noise_threshold: 0.02`) and speech/silence detection before sending audio to **Saaras v3 STT**.
3. **Tool-Calling Agent ([`voice_agent.py`](backend/agents/voice_agent.py), [`tools.py`](backend/agents/tools.py)):** **Kimi K2** (`kimi-k2-instruct`) processes multi-turn session history from Redis/PostgreSQL and executes structured tools (`search_menu`, `add_to_cart`, `remove_from_cart`, `get_cart`, `validate_order`, `checkout`, `get_recommendations`).
4. **Streaming TTS & Interrupt Handling ([`tts_service.py`](backend/services/tts_service.py)):** **Bulbul v3** synthesizes `pcm_16000` audio chunks streamed back to the browser; `interrupt`, `pause`, and `resume` signals enable barge-in dialogue control.

---

## Models & AI Services Used

| Component | Model / Algorithm | Purpose & How It Is Used | Implementation |
| :--- | :--- | :--- | :--- |
| **Speech-to-Text (STT)** | **Saaras v3** | Transcribes 16 kHz PCM audio after noise filtering and adaptive silence buffering | [`backend/services/stt_service.py`](backend/services/stt_service.py) |
| **Conversational LLM** | **Kimi K2** (`kimi-k2-instruct`) | Multi-turn dialogue management (`32K` context) with OpenAI-style tool calling | [`backend/services/llm_service.py`](backend/services/llm_service.py) |
| **Text-to-Speech (TTS)** | **Bulbul v3** (`pcm_16000`) | Streams synthesized voice responses chunk-by-chunk over WebSocket | [`backend/services/tts_service.py`](backend/services/tts_service.py) |
| **Semantic Menu Search** | `text-embedding-3-small` (`1536`-dim) + **Pinecone** | Embeds menu items and natural-language queries for cosine-similarity fuzzy matching | [`backend/services/vector_service.py`](backend/services/vector_service.py) |
| **Smart Recommendations** | **FP-Growth** (`mlxtend`) | Mines association rules (`min_support=0.05`, `min_confidence=0.3`) from completed orders | [`backend/services/recommendation_service.py`](backend/services/recommendation_service.py) |
| **Multilingual Reporting** | **Google Gemini** (`gemini-1.5-pro`) | Generates natural-language sales/menu performance reports (with deterministic fallback) | [`backend/routers/reports.py`](backend/routers/reports.py) |

---

## Data Sources, Schema & Seeding

This application uses **operational restaurant POS & order-history data** stored in **PostgreSQL 15**, cached in **Redis 7**, and indexed in **Pinecone** (no external static ML dataset is required):

- **Database Schema ([`migrations/001_initial.sql`](migrations/001_initial.sql), [`backend/models/database.py`](backend/models/database.py)):**
  - `menu_items`: Restaurant catalog (name, description, price, category, tags, calories, allergens, prep time, availability).
  - `voice_sessions`: Active conversation history, state (`active`, `paused`, `completed`), and customer metadata.
  - `cart_items` & `orders` / `order_items`: Real-time cart state and confirmed POS orders.
- **Seed Data ([`scripts/seed_menu.py`](scripts/seed_menu.py)):**
  - Populates **15 sample restaurant menu items** (burgers, wraps, sides, beverages, desserts) and **20 historical order baskets** so the **FP-Growth** recommender and Pinecone index can be initialized immediately out of the box.
- **Caching Layer ([`backend/services/cache_service.py`](backend/services/cache_service.py)):**
  - Preloads menu items (`TTL 3600s`), stores session state (`TTL 1800s`), and caches recommendation outputs (`TTL 900s`).

---

## Design Benchmark Targets

Project performance targets from the system design specification (requires live external API keys for Saaras v3, Kimi K2, Bulbul v3, Pinecone, and Gemini to benchmark end-to-end):

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

# 4. Seed the menu & historical order baskets (in another terminal)
docker compose exec backend python scripts/seed_menu.py

# 5. Open the app
# Frontend: http://localhost:3000 | API Docs: http://localhost:8000/docs
```

### Manual Setup

#### Backend (`Python 3.11+`, `PostgreSQL 15+`, `Redis 7+`)

```bash
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env

psql -U voiceserve -d voiceserve -f migrations/001_initial.sql
python scripts/seed_menu.py
uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload
```

#### Frontend (`Node.js 18+`)

```bash
cd frontend
npm install
npm run dev
```

---

## API & WebSocket Reference

Interactive Swagger docs are served at `http://localhost:8000/docs`.

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
