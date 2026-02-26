/** Email verification page — processes token from URL. */

import { useState, useEffect } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { apiJson } from '../api/client';

export function VerifyEmailPage() {
  const [params] = useSearchParams();
  const token = params.get('token') || '';
  const [status, setStatus] = useState<'loading' | 'success' | 'error'>('loading');
  const [message, setMessage] = useState('');

  useEffect(() => {
    if (!token) {
      setStatus('error');
      setMessage('Missing verification token.');
      return;
    }
    apiJson(`/auth/verify-email?token=${token}`, { method: 'POST' })
      .then(() => {
        setStatus('success');
        setMessage('Email verified successfully!');
      })
      .catch((e: any) => {
        setStatus('error');
        setMessage(e.message || 'Verification failed. The link may have expired.');
      });
  }, [token]);

  return (
    <div className="auth-page">
      <div className="auth-card">
        <h1>🎙 Voice Studio</h1>
        <h2>Email Verification</h2>
        {status === 'loading' && <p>Verifying...</p>}
        {status === 'success' && (
          <>
            <p className="text-green">✓ {message}</p>
            <p className="auth-link"><Link to="/login">Sign In</Link></p>
          </>
        )}
        {status === 'error' && (
          <>
            <p className="error">{message}</p>
            <p className="auth-link"><Link to="/login">Back to Sign In</Link></p>
          </>
        )}
      </div>
    </div>
  );
}
