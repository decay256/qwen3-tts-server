/** Account settings — change password, email, delete account. */

import { useState, useEffect, type FormEvent } from 'react';
import { useNavigate } from 'react-router-dom';
import { apiJson } from '../api/client';

interface Props {
  onLogout: () => void;
}

interface Account {
  id: string;
  email: string;
  is_verified: boolean;
  created_at: string;
}

export function AccountPage({ onLogout }: Props) {
  const navigate = useNavigate();
  const [account, setAccount] = useState<Account | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Password
  const [currentPw, setCurrentPw] = useState('');
  const [newPw, setNewPw] = useState('');
  const [changingPw, setChangingPw] = useState(false);

  // Email
  const [newEmail, setNewEmail] = useState('');
  const [emailPw, setEmailPw] = useState('');
  const [changingEmail, setChangingEmail] = useState(false);

  // Delete
  const [deletePw, setDeletePw] = useState('');
  const [deleting, setDeleting] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);

  useEffect(() => {
    apiJson<Account>('/api/v1/account').then(setAccount).catch(() => {});
  }, []);

  const flash = (message: string, isError = false) => {
    if (isError) { setError(message); setMsg(null); }
    else { setMsg(message); setError(null); }
    setTimeout(() => { setMsg(null); setError(null); }, 5000);
  };

  const changePassword = async (e: FormEvent) => {
    e.preventDefault();
    setChangingPw(true);
    try {
      await apiJson('/api/v1/account/change-password', {
        method: 'POST',
        body: JSON.stringify({ current_password: currentPw, new_password: newPw }),
      });
      flash('Password changed successfully');
      setCurrentPw(''); setNewPw('');
    } catch (e: any) { flash(e.message, true); }
    finally { setChangingPw(false); }
  };

  const changeEmail = async (e: FormEvent) => {
    e.preventDefault();
    setChangingEmail(true);
    try {
      await apiJson('/api/v1/account/change-email', {
        method: 'POST',
        body: JSON.stringify({ email: newEmail, password: emailPw }),
      });
      flash('Email updated');
      setNewEmail(''); setEmailPw('');
      const a = await apiJson<Account>('/api/v1/account');
      setAccount(a);
    } catch (e: any) { flash(e.message, true); }
    finally { setChangingEmail(false); }
  };

  const deleteAccount = async () => {
    setDeleting(true);
    try {
      await apiJson('/api/v1/account/delete', {
        method: 'POST',
        body: JSON.stringify({ password: deletePw }),
      });
      onLogout();
      navigate('/login');
    } catch (e: any) { flash(e.message, true); setDeleting(false); }
  };

  if (!account) return <div className="loading">Loading...</div>;

  return (
    <div className="account-page">
      <button onClick={() => navigate('/')} className="btn-back">← Back</button>
      <h2>Account Settings</h2>

      {msg && <div className="flash success">{msg}</div>}
      {error && <div className="flash error">{error}</div>}

      <section>
        <h3>Profile</h3>
        <div className="info-row"><span>Email:</span> <strong>{account.email}</strong></div>
        <div className="info-row"><span>Verified:</span> <span className={account.is_verified ? 'text-green' : 'text-red'}>{account.is_verified ? 'Yes' : 'No'}</span></div>
        <div className="info-row"><span>Member since:</span> {new Date(account.created_at).toLocaleDateString()}</div>
      </section>

      <section>
        <h3>Change Password</h3>
        <form onSubmit={changePassword}>
          <input type="password" placeholder="Current password" value={currentPw} onChange={e => setCurrentPw(e.target.value)} required />
          <input type="password" placeholder="New password (8+ characters)" value={newPw} onChange={e => setNewPw(e.target.value)} required minLength={8} />
          <button type="submit" disabled={changingPw} className="btn-primary">
            {changingPw ? 'Changing...' : 'Change Password'}
          </button>
        </form>
      </section>

      <section>
        <h3>Change Email</h3>
        <form onSubmit={changeEmail}>
          <input type="email" placeholder="New email" value={newEmail} onChange={e => setNewEmail(e.target.value)} required />
          <input type="password" placeholder="Confirm with password" value={emailPw} onChange={e => setEmailPw(e.target.value)} required />
          <button type="submit" disabled={changingEmail} className="btn-primary">
            {changingEmail ? 'Updating...' : 'Update Email'}
          </button>
        </form>
      </section>

      <section className="danger-zone">
        <h3>⚠️ Danger Zone</h3>
        {!confirmDelete ? (
          <button onClick={() => setConfirmDelete(true)} className="btn-danger">Delete Account</button>
        ) : (
          <div>
            <p className="warning-text">This will permanently delete your account and all characters. This cannot be undone.</p>
            <input type="password" placeholder="Confirm with password" value={deletePw} onChange={e => setDeletePw(e.target.value)} />
            <div className="btn-row">
              <button onClick={deleteAccount} disabled={deleting} className="btn-danger">
                {deleting ? 'Deleting...' : 'Permanently Delete'}
              </button>
              <button onClick={() => { setConfirmDelete(false); setDeletePw(''); }} className="btn-secondary">Cancel</button>
            </div>
          </div>
        )}
      </section>
    </div>
  );
}
