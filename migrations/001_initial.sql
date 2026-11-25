-- VoiceServe AI Initial PostgreSQL Schema
-- Matches backend/models/database.py

CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- ── Menu Items ───────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS menu_items (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(255) NOT NULL,
    description TEXT,
    price NUMERIC(10, 2) NOT NULL,
    category VARCHAR(100) NOT NULL,
    tags VARCHAR[] DEFAULT '{}',
    is_available BOOLEAN NOT NULL DEFAULT TRUE,
    image_url VARCHAR(500),
    calories INTEGER,
    allergens VARCHAR[] DEFAULT '{}',
    preparation_time_minutes INTEGER,
    embedding_synced BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_menu_items_name ON menu_items (name);
CREATE INDEX IF NOT EXISTS ix_menu_items_category ON menu_items (category);

-- ── Voice Sessions ───────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    conversation_history JSON NOT NULL DEFAULT '[]'::json,
    context JSON NOT NULL DEFAULT '{}'::json,
    language VARCHAR(10) NOT NULL DEFAULT 'en-IN',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_active_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ── Orders ───────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS orders (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID REFERENCES sessions(id) ON DELETE SET NULL,
    status VARCHAR(50) NOT NULL DEFAULT 'pending',
    total_amount NUMERIC(10, 2) NOT NULL DEFAULT 0.00,
    notes TEXT,
    metadata JSON NOT NULL DEFAULT '{}'::json,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_orders_session_id ON orders (session_id);
CREATE INDEX IF NOT EXISTS ix_orders_status ON orders (status);

-- ── Order Items ──────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS order_items (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    order_id UUID NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    menu_item_id UUID NOT NULL REFERENCES menu_items(id) ON DELETE RESTRICT,
    quantity INTEGER NOT NULL DEFAULT 1,
    unit_price NUMERIC(10, 2) NOT NULL,
    customizations JSON NOT NULL DEFAULT '{}'::json,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_order_items_order_id ON order_items (order_id);

-- ── Cart Items ───────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS cart_items (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    menu_item_id UUID NOT NULL REFERENCES menu_items(id) ON DELETE CASCADE,
    quantity INTEGER NOT NULL DEFAULT 1,
    customizations JSON NOT NULL DEFAULT '{}'::json,
    added_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_cart_session_item UNIQUE (session_id, menu_item_id)
);

CREATE INDEX IF NOT EXISTS ix_cart_items_session_id ON cart_items (session_id);

-- ── Auto-update updated_at trigger ───────────────────────────────────────────
CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_menu_items_updated_at ON menu_items;
CREATE TRIGGER trg_menu_items_updated_at
    BEFORE UPDATE ON menu_items
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS trg_orders_updated_at ON orders;
CREATE TRIGGER trg_orders_updated_at
    BEFORE UPDATE ON orders
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();
