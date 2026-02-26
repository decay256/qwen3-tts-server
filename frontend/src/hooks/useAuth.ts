/** Auth hook — login, register, logout. */

import { useState, useCallback } from 'react';
import { apiJson, setTokens, isLoggedIn } from '../api/client';

export function useAuth() {
  const [loggedIn, setLoggedIn] = useState(isLoggedIn());
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const login = useCallback(async (email: string, password: string) => {
    setLoading(true);
    setError(null);
    try {
      const data = await apiJson<{ access_token: string; refresh_token: string }>(
        '/auth/login',
        { method: 'POST', body: JSON.stringify({ email, password }) }
      );
      setTokens(data);
      setLoggedIn(true);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, []);

  const register = useCallback(async (email: string, password: string) => {
    setLoading(true);
    setError(null);
    try {
      await apiJson('/auth/register', {
        method: 'POST',
        body: JSON.stringify({ email, password }),
      });
      // Auto-login after register
      await login(email, password);
    } catch (e: any) {
      setError(e.message);
      setLoading(false);
    }
  }, [login]);

  const logout = useCallback(() => {
    setTokens(null);
    setLoggedIn(false);
  }, []);

  return { loggedIn, login, register, logout, error, loading };
}
