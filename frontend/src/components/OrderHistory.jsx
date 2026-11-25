import React from 'react';
import { ClipboardList, RefreshCw } from 'lucide-react';

const STATUS_NEXT = {
  pending: 'confirmed',
  confirmed: 'preparing',
  preparing: 'ready',
  ready: 'delivered',
};

export default function OrderHistory({ orders, loading, onRefresh, onUpdateStatus }) {
  return (
    <section className="panel">
      <div className="panel-header">
        <div className="panel-title">
          <ClipboardList size={18} color="#f59e0b" />
          <span>Order History ({orders.length})</span>
        </div>
        <button type="button" className="btn" onClick={onRefresh} disabled={loading}>
          <RefreshCw size={14} />
          Refresh
        </button>
      </div>

      {loading ? (
        <div className="empty-state">Loading orders...</div>
      ) : orders.length === 0 ? (
        <div className="empty-state">No orders placed yet.</div>
      ) : (
        <div className="orders-grid">
          {orders.map((order) => {
            const nextStatus = STATUS_NEXT[order.status];
            return (
              <div key={order.id} className="order-card">
                <div className="panel-header">
                  <span style={{ fontWeight: 600, fontSize: '0.88rem' }}>
                    Order #{order.id.slice(0, 8)}
                  </span>
                  <span className="status-badge connected">{order.status}</span>
                </div>

                <div style={{ fontSize: '0.78rem', color: '#94a3b8' }}>
                  {new Date(order.created_at).toLocaleString()}
                </div>

                <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                  {(order.items || []).map((item) => (
                    <div
                      key={item.id}
                      style={{
                        display: 'flex',
                        justifyContent: 'space-between',
                        fontSize: '0.84rem',
                      }}
                    >
                      <span>
                        {item.quantity}x {item.menu_item?.name || item.menu_item_id}
                      </span>
                      <span>
                        ${(Number(item.unit_price) * item.quantity).toFixed(2)}
                      </span>
                    </div>
                  ))}
                </div>

                {order.notes && (
                  <div style={{ fontSize: '0.78rem', color: '#cbd5e1' }}>
                    Note: {order.notes}
                  </div>
                )}

                <div className="total-line" style={{ borderTop: '1px solid #253047', paddingTop: 8 }}>
                  <span>Total</span>
                  <span className="price">${Number(order.total_amount).toFixed(2)}</span>
                </div>

                {nextStatus && onUpdateStatus && (
                  <button
                    type="button"
                    className="btn"
                    onClick={() => onUpdateStatus(order.id, nextStatus)}
                  >
                    Mark as {nextStatus}
                  </button>
                )}
              </div>
            );
          })}
        </div>
      )}
    </section>
  );
}
