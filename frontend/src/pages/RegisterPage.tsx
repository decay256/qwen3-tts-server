/** Register page. */

import { useState, type FormEvent } from 'react';
import { Link } from 'react-router-dom';

interface Props {
  onRegister: (email: string, password: string) => Promise<void>;
  error: string | null;
  loading: boolean;
}

export function RegisterPage({ onRegister, error, loading }: Props) {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [localError, setLocalError] = useState<string | null>(null);

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault();
    if (password !== confirm) {
      setLocalError('Passwords do not match');
      return;
    }
    setLocalError(null);
    onRegister(email, password);
  };

  return (
    <div className="auth-page">
      <div className="auth-card">
        <h1>🎙 Voice Studio</h1>
        <h2>Create Account</h2>
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
            placeholder="Password (8+ characters)"
            value={password}
            onChange={e => setPassword(e.target.value)}
            required
            minLength={8}
          />
          <input
            type="password"
            placeholder="Confirm password"
            value={confirm}
            onChange={e => setConfirm(e.target.value)}
            required
          />
          <button type="submit" disabled={loading}>
            {loading ? 'Creating...' : 'Create Account'}
          </button>
        </form>
        {(error || localError) && <p className="error">{localError || error}</p>}
        <p className="auth-link">
          Already have an account? <Link to="/login">Sign In</Link>
        </p>
      </div>
    </div>
  );
}
