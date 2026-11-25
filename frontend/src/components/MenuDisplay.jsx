import React, { useMemo, useState } from 'react';
import { Plus, Search, UtensilsCrossed } from 'lucide-react';

export default function MenuDisplay({ items, loading, onAddToCart, onSemanticSearch }) {
  const [selectedCategory, setSelectedCategory] = useState('All');
  const [query, setQuery] = useState('');

  const categories = useMemo(() => {
    const unique = Array.from(new Set(items.map((item) => item.category))).sort();
    return ['All', ...unique];
  }, [items]);

  const filteredItems = useMemo(() => {
    const q = query.trim().toLowerCase();
    return items.filter((item) => {
      const catMatch =
        selectedCategory === 'All' || item.category === selectedCategory;
      if (!catMatch) return false;
      if (!q) return true;
      return (
        item.name.toLowerCase().includes(q) ||
        (item.description || '').toLowerCase().includes(q) ||
        (item.tags || []).some((t) => t.toLowerCase().includes(q))
      );
    });
  }, [items, selectedCategory, query]);

  const handleSearchKeyDown = (e) => {
    if (e.key === 'Enter' && onSemanticSearch) {
      onSemanticSearch(query);
    }
  };

  return (
    <section className="panel">
      <div className="panel-header">
        <div className="panel-title">
          <UtensilsCrossed size={18} color="#f59e0b" />
          <span>Menu ({filteredItems.length})</span>
        </div>
      </div>

      <div className="text-input-row">
        <input
          className="input"
          type="text"
          placeholder="Search menu (e.g. spicy, vegan, burger)..."
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={handleSearchKeyDown}
        />
        {onSemanticSearch && (
          <button
            type="button"
            className="btn"
            onClick={() => onSemanticSearch(query)}
            title="Semantic search"
          >
            <Search size={15} />
          </button>
        )}
      </div>

      <div className="category-pills">
        {categories.map((cat) => (
          <button
            key={cat}
            type="button"
            className={`pill ${selectedCategory === cat ? 'active' : ''}`}
            onClick={() => setSelectedCategory(cat)}
          >
            {cat}
          </button>
        ))}
      </div>

      <div className="menu-list">
        {loading ? (
          <div className="empty-state">Loading menu...</div>
        ) : filteredItems.length === 0 ? (
          <div className="empty-state">No matching menu items found.</div>
        ) : (
          filteredItems.map((item) => (
            <div key={item.id} className="menu-card">
              <div>
                <h4>{item.name}</h4>
                <p className="menu-desc">{item.description}</p>
                <div className="tag-row">
                  <span className="tag">{item.category}</span>
                  {(item.tags || []).map((tag) => (
                    <span key={tag} className="tag">
                      {tag}
                    </span>
                  ))}
                  {item.calories != null && (
                    <span className="tag">{item.calories} kcal</span>
                  )}
                </div>
              </div>

              <div className="menu-meta">
                <span className="price">${Number(item.price).toFixed(2)}</span>
                <button
                  type="button"
                  className="btn btn-primary"
                  disabled={!item.is_available}
                  onClick={() => onAddToCart(item.id)}
                >
                  <Plus size={14} />
                  {item.is_available ? 'Add' : 'Sold Out'}
                </button>
              </div>
            </div>
          ))
        )}
      </div>
    </section>
  );
}
