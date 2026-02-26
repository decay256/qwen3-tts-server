/** App layout with header and nav. */

import { Outlet, Link, useNavigate } from 'react-router-dom';

interface Props {
  onLogout: () => void;
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
          <Link to="/config">Config</Link>
          <Link to="/account">Account</Link>
          <button onClick={handleLogout} className="btn-link">Logout</button>
        </nav>
      </header>
      <main className="app-main">
        <Outlet />
      </main>
    </div>
  );
}
