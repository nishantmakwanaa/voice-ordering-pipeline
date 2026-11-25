import React, { useState } from 'react';
import { CheckCircle2, ShoppingCart, Sparkles, Trash2 } from 'lucide-react';

export default function CartDisplay({
  cart,
  recommendations,
  onUpdateQuantity,
  onRemoveItem,
  onAddRecommendation,
  onCheckout,
}) {
  const [notes, setNotes] = useState('');
  const [submitting, setSubmitting] = useState(false);

  const items = cart?.items || [];
  const total = Number(cart?.total || 0);

  const handleCheckout = async () => {
    setSubmitting(true);
    try {
      await onCheckout(notes);
      setNotes('');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <section className="panel">
      <div className="panel-header">
        <div className="panel-title">
          <ShoppingCart size={18} color="#f59e0b" />
          <span>Your Cart ({cart?.item_count || 0})</span>
        </div>
      </div>

      {items.length === 0 ? (
        <div className="empty-state">
          Your cart is empty. Add items from the menu or ask VoiceServe!
        </div>
      ) : (
        <div className="cart-items">
          {items.map((item) => {
            const unitPrice = Number(item.menu_item?.price || 0);
            return (
              <div key={item.id} className="cart-row">
                <div>
                  <div style={{ fontWeight: 600, fontSize: '0.9rem' }}>
                    {item.menu_item?.name || 'Menu Item'}
                  </div>
                  <div style={{ fontSize: '0.78rem', color: '#94a3b8' }}>
                    ${unitPrice.toFixed(2)} each · $
                    {(unitPrice * item.quantity).toFixed(2)}
                  </div>
                </div>

                <div className="qty-controls">
                  <button
                    type="button"
                    className="qty-btn"
                    onClick={() => onUpdateQuantity(item.menu_item_id, -1)}
                    aria-label="Decrease quantity"
                  >
                    -
                  </button>
                  <span style={{ minWidth: 18, textAlign: 'center', fontSize: '0.88rem' }}>
                    {item.quantity}
                  </span>
                  <button
                    type="button"
                    className="qty-btn"
                    onClick={() => onUpdateQuantity(item.menu_item_id, 1)}
                    aria-label="Increase quantity"
                  >
                    +
                  </button>
                  <button
                    type="button"
                    className="qty-btn"
                    onClick={() => onRemoveItem(item.menu_item_id)}
                    title="Remove item"
                  >
                    <Trash2 size={13} color="#fca5a5" />
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      )}

      {recommendations && recommendations.length > 0 && (
        <div className="recs-box">
          <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: '0.82rem', fontWeight: 600, color: '#6ee7b7' }}>
            <Sparkles size={14} />
            <span>Recommended Pairings</span>
          </div>
          {recommendations.slice(0, 3).map((rec) => (
            <div key={rec.menu_item.id} className="rec-item">
              <div>
                <div style={{ fontWeight: 500 }}>{rec.menu_item.name}</div>
                <div style={{ fontSize: '0.73rem', color: '#94a3b8' }}>
                  ${Number(rec.menu_item.price).toFixed(2)} · {rec.reason}
                </div>
              </div>
              <button
                type="button"
                className="btn"
                style={{ padding: '4px 9px', fontSize: '0.76rem' }}
                onClick={() => onAddRecommendation(rec.menu_item.id)}
              >
                + Add
              </button>
            </div>
          ))}
        </div>
      )}

      <div className="cart-summary">
        <input
          className="input"
          type="text"
          placeholder="Special instructions (no onions, extra napkins)..."
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
        />
        <div className="total-line">
          <span>Total</span>
          <span className="price">${total.toFixed(2)}</span>
        </div>
        <button
          type="button"
          className="btn btn-success"
          disabled={items.length === 0 || submitting}
          onClick={handleCheckout}
        >
          <CheckCircle2 size={16} />
          {submitting ? 'Placing Order...' : 'Place Order'}
        </button>
      </div>
    </section>
  );
}
