/** App layout with header, nav, and persistent connection status. */

import { useState, useEffect, useCallback } from 'react';
import { Outlet, Link, useNavigate, useLocation } from 'react-router-dom';
import { ConnectionStatus } from './ConnectionStatus';
import { apiJson } from '../api/client';
import type { DraftSummary } from '../api/types';

interface Props {
  onLogout: () => void;
}

/** Small queue counter — polls /api/v1/drafts on every navigation and every 3s while active. */
function QueueCounter() {
  const [count, setCount] = useState(0);
  const location = useLocation();

  const fetchCount = useCallback(async () => {
    try {
      const data = await apiJson<{ drafts: DraftSummary[]; total: number }>(
        '/api/v1/drafts?limit=50'
      );
      const active = (data.drafts || []).filter(
        d => d.status === 'pending' || d.status === 'generating'
      ).length;
      setCount(active);
    } catch {
      // ignore — backend may not be ready yet
    }
  }, []);

  // Refresh on every navigation
  useEffect(() => {
    fetchCount();
  }, [location.pathname, fetchCount]);

  // Poll every 3s when there are active drafts
  useEffect(() => {
    if (count === 0) return;
    const id = setInterval(fetchCount, 3_000);
    return () => clearInterval(id);
  }, [count, fetchCount]);

  if (count === 0) return null;
  return (
    <span
      className="nav-queue-badge"
      title={`${count} draft${count !== 1 ? 's' : ''} generating`}
    >
      {count}
    </span>
  );
}

export function Layout({ onLogout }: Props) {
  const navigate = useNavigate();

  const handleLogout = () => {
    onLogout();
    navigate('/login');
  };

  return (
    <div className="app">
      <header className="app-header">
        <Link to="/" className="logo">🎙 Voice Studio</Link>
        <nav>
          <Link to="/">Dashboard</Link>
          <span className="nav-drafts-link">
            <Link to="/">Drafts</Link>
            <QueueCounter />
          </span>
          <Link to="/config">Config</Link>
          <Link to="/account">Account</Link>
          <button onClick={handleLogout} className="btn-link">Logout</button>
        </nav>
      </header>
      {/* Connection status — visible on every page (Sprint 5) */}
      <div className="navbar-status">
        <ConnectionStatus />
      </div>
      <main className="app-main">
        <Outlet />
      </main>
    </div>
  );
}
