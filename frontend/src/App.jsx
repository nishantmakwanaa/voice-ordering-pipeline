import React, { useCallback, useEffect, useState } from 'react';
import { ClipboardList, Headphones, Utensils } from 'lucide-react';
import CartDisplay from './components/CartDisplay.jsx';
import MenuDisplay from './components/MenuDisplay.jsx';
import OrderHistory from './components/OrderHistory.jsx';
import VoiceInterface from './components/VoiceInterface.jsx';
import { useVoiceSocket } from './hooks/useVoiceSocket.js';

const API_BASE = (import.meta.env.VITE_API_URL || '').replace(/\/$/, '');

function getOrCreateSessionId() {
  const key = 'voiceserve_session_id';
  let id = localStorage.getItem(key);
  if (!id) {
    id = crypto.randomUUID
      ? crypto.randomUUID()
      : 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
          const r = (Math.random() * 16) | 0;
          const v = c === 'x' ? r : (r & 0x3) | 0x8;
          return v.toString(16);
        });
    localStorage.setItem(key, id);
  }
  return id;
}

export default function App() {
  const [sessionId] = useState(getOrCreateSessionId);
  const [activeTab, setActiveTab] = useState('order'); // order | orders
  const [menuItems, setMenuItems] = useState([]);
  const [menuLoading, setMenuLoading] = useState(true);
  const [cart, setCart] = useState({ session_id: sessionId, items: [], total: '0.00', item_count: 0 });
  const [recommendations, setRecommendations] = useState([]);
  const [orders, setOrders] = useState([]);
  const [ordersLoading, setOrdersLoading] = useState(false);
  const [bannerError, setBannerError] = useState(null);

  const fetchRecommendations = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/recommendations/${sessionId}`);
      if (res.ok) {
        const data = await res.json();
        setRecommendations(data.recommendations || []);
      }
    } catch {
      // non-fatal
    }
  }, [sessionId]);

  const handleCartSync = useCallback(
    (updatedCart) => {
      setCart(updatedCart);
      fetchRecommendations();
    },
    [fetchRecommendations]
  );

  const voice = useVoiceSocket(sessionId, { onCartUpdate: handleCartSync });

  const fetchMenu = useCallback(async () => {
    setMenuLoading(true);
    try {
      const res = await fetch(`${API_BASE}/menu?page_size=100`);
      if (res.ok) {
        const data = await res.json();
        setMenuItems(data.items || []);
      }
    } catch {
      setBannerError('Unable to reach backend API. Start FastAPI on port 8000.');
    } finally {
      setMenuLoading(false);
    }
  }, []);

  const fetchCart = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/cart/${sessionId}`);
      if (res.ok) {
        const data = await res.json();
        setCart(data);
      }
    } catch {
      // ignore initial offline error
    }
  }, [sessionId]);

  const fetchOrders = useCallback(async () => {
    setOrdersLoading(true);
    try {
      const res = await fetch(`${API_BASE}/orders?page_size=25`);
      if (res.ok) {
        const data = await res.json();
        setOrders(data.orders || []);
      }
    } finally {
      setOrdersLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchMenu();
    fetchCart();
    fetchRecommendations();
    fetchOrders();
  }, [fetchMenu, fetchCart, fetchRecommendations, fetchOrders]);

  const handleSemanticSearch = async (query) => {
    if (!query.trim()) {
      fetchMenu();
      return;
    }
    const res = await fetch(
      `${API_BASE}/menu/search?q=${encodeURIComponent(query.trim())}&limit=15`
    );
    if (res.ok) {
      const hits = await res.json();
      setMenuItems(hits);
    }
  };

  const handleAddToCart = async (menuItemId) => {
    setBannerError(null);
    const res = await fetch(`${API_BASE}/cart/${sessionId}/add`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ menu_item_id: menuItemId, quantity: 1 }),
    });
    if (res.ok) {
      const updated = await res.json();
      handleCartSync(updated);
    } else {
      const err = await res.json().catch(() => ({}));
      setBannerError(err.detail || 'Could not add item to cart.');
    }
  };

  const handleUpdateQuantity = async (menuItemId, delta) => {
    if (delta > 0) {
      await handleAddToCart(menuItemId);
      return;
    }
    const res = await fetch(
      `${API_BASE}/cart/${sessionId}/item/${menuItemId}?quantity=1`,
      { method: 'DELETE' }
    );
    if (res.ok) {
      const updated = await res.json();
      handleCartSync(updated);
    }
  };

  const handleRemoveItem = async (menuItemId) => {
    const res = await fetch(`${API_BASE}/cart/${sessionId}/item/${menuItemId}`, {
      method: 'DELETE',
    });
    if (res.ok) {
      const updated = await res.json();
      handleCartSync(updated);
    }
  };

  const handleCheckout = async (notes) => {
    setBannerError(null);
    const res = await fetch(`${API_BASE}/cart/${sessionId}/checkout`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session_id: sessionId, notes: notes || null }),
    });
    if (res.ok) {
      await fetchCart();
      await fetchOrders();
      setActiveTab('orders');
    } else {
      const err = await res.json().catch(() => ({}));
      setBannerError(err.detail || 'Checkout failed.');
    }
  };

  const handleUpdateOrderStatus = async (orderId, nextStatus) => {
    const res = await fetch(`${API_BASE}/orders/${orderId}/status`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ status: nextStatus }),
    });
    if (res.ok) {
      fetchOrders();
    }
  };

  return (
    <div className="app-shell">
      <header className="app-header">
        <div className="brand">
          <div className="brand-badge">VS</div>
          <div>
            <h1>VoiceServe AI</h1>
            <p>Real-Time Voice Ordering · Saaras v3 · Kimi K2 · Bulbul v3</p>
          </div>
        </div>

        <div className="header-controls">
          <nav className="nav-tabs">
            <button
              type="button"
              className={`nav-tab ${activeTab === 'order' ? 'active' : ''}`}
              onClick={() => setActiveTab('order')}
            >
              <Utensils size={15} />
              Order &amp; Voice
            </button>
            <button
              type="button"
              className={`nav-tab ${activeTab === 'orders' ? 'active' : ''}`}
              onClick={() => {
                setActiveTab('orders');
                fetchOrders();
              }}
            >
              <ClipboardList size={15} />
              Order History ({orders.length})
            </button>
          </nav>

          <span className="session-pill">
            <Headphones size={12} style={{ marginRight: 5, verticalAlign: 'middle' }} />
            Session {sessionId.slice(0, 8)}
          </span>
        </div>
      </header>

      {bannerError && (
        <div className="error-banner" style={{ marginBottom: 16 }}>
          {bannerError}
        </div>
      )}

      {activeTab === 'order' ? (
        <main className="dashboard-grid">
          <VoiceInterface voice={voice} />
          <MenuDisplay
            items={menuItems}
            loading={menuLoading}
            onAddToCart={handleAddToCart}
            onSemanticSearch={handleSemanticSearch}
          />
          <CartDisplay
            cart={cart}
            recommendations={recommendations}
            onUpdateQuantity={handleUpdateQuantity}
            onRemoveItem={handleRemoveItem}
            onAddRecommendation={handleAddToCart}
            onCheckout={handleCheckout}
          />
        </main>
      ) : (
        <OrderHistory
          orders={orders}
          loading={ordersLoading}
          onRefresh={fetchOrders}
          onUpdateStatus={handleUpdateOrderStatus}
        />
      )}
    </div>
  );
}
