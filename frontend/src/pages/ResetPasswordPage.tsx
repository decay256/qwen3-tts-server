/** Reset password — enter new password with token from URL. */

import { useState, type FormEvent } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { apiJson } from '../api/client';

export function ResetPasswordPage() {
  const [params] = useSearchParams();
  const token = params.get('token') || '';
  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [done, setDone] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    if (password !== confirm) {
      setError('Passwords do not match');
      return;
    }
    setLoading(true);
    setError(null);
    try {
      await apiJson('/auth/reset-confirm', {
        method: 'POST',
        body: JSON.stringify({ token, new_password: password }),
      });
      setDone(true);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  };

  if (!token) {
    return (
      <div className="auth-page">
        <div className="auth-card">
          <h2>Invalid Reset Link</h2>
          <p>This link is missing the reset token.</p>
          <p className="auth-link"><Link to="/forgot-password">Request a new reset link</Link></p>
        </div>
      </div>
    );
  }

  return (
    <div className="auth-page">
      <div className="auth-card">
        <h1>🎙 Voice Studio</h1>
        <h2>Set New Password</h2>
        {done ? (
          <>
            <p>Password reset successfully!</p>
            <p className="auth-link"><Link to="/login">Sign In</Link></p>
          </>
        ) : (
          <form onSubmit={handleSubmit}>
            <input
              type="password"
              placeholder="New password (8+ characters)"
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
              {loading ? 'Resetting...' : 'Reset Password'}
            </button>
          </form>
        )}
        {error && <p className="error">{error}</p>}
      </div>
    </div>
  );
}
