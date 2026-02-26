/** Login page. */

import { useState, type FormEvent } from 'react';
import { Link } from 'react-router-dom';

interface Props {
  onLogin: (email: string, password: string) => Promise<void>;
  error: string | null;
  loading: boolean;
}

export function LoginPage({ onLogin, error, loading }: Props) {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault();
    onLogin(email, password);
  };

  return (
    <div className="auth-page">
      <div className="auth-card">
        <h1>🎙 Voice Studio</h1>
        <h2>Sign In</h2>
        <form onSubmit={handleSubmit}>
          <input
            type="email"
            placeholder="Email"
            value={email}
            onChange={e => setEmail(e.target.value)}
            required
          />
          <input
            type="password"
            placeholder="Password"
            value={password}
            onChange={e => setPassword(e.target.value)}
            required
            minLength={8}
          />
          <button type="submit" disabled={loading}>
            {loading ? 'Signing in...' : 'Sign In'}
          </button>
        </form>
        {error && <p className="error">{error}</p>}
        <p className="auth-link">
          <Link to="/forgot-password">Forgot password?</Link>
        </p>
        <p className="auth-link">
          Don't have an account? <Link to="/register">Sign Up</Link>
        </p>
      </div>
    </div>
  );
}
