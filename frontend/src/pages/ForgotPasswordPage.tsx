/** Forgot password — request reset email. */

import { useState, type FormEvent } from 'react';
import { Link } from 'react-router-dom';
import { apiJson } from '../api/client';

export function ForgotPasswordPage() {
  const [email, setEmail] = useState('');
  const [sent, setSent] = useState(false);
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setLoading(true);
    try {
      await apiJson('/auth/reset-request', {
        method: 'POST',
        body: JSON.stringify({ email }),
      });
      setSent(true);
    } catch {
      // Always show success (don't reveal if email exists)
      setSent(true);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="auth-page">
      <div className="auth-card">
        <h1>🎙 Voice Studio</h1>
        <h2>Reset Password</h2>
        {sent ? (
          <>
            <p>If that email is registered, a reset link has been sent. Check your inbox.</p>
            <p className="auth-link"><Link to="/login">Back to Sign In</Link></p>
          </>
        ) : (
          <form onSubmit={handleSubmit}>
            <input
              type="email"
              placeholder="Email"
              value={email}
              onChange={e => setEmail(e.target.value)}
              required
            />
            <button type="submit" disabled={loading}>
              {loading ? 'Sending...' : 'Send Reset Link'}
            </button>
          </form>
        )}
        <p className="auth-link"><Link to="/login">Back to Sign In</Link></p>
      </div>
    </div>
  );
}
