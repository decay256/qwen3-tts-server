import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { useAuth } from './hooks/useAuth';
import { Layout } from './components/Layout';
import { LoginPage } from './pages/LoginPage';
import { RegisterPage } from './pages/RegisterPage';
import { ForgotPasswordPage } from './pages/ForgotPasswordPage';
import { ResetPasswordPage } from './pages/ResetPasswordPage';
import { VerifyEmailPage } from './pages/VerifyEmailPage';
import { DashboardPage } from './pages/DashboardPage';
import { CharacterPage } from './pages/CharacterPage';
import { AccountPage } from './pages/AccountPage';
import { ConfigPage } from './pages/ConfigPage';
import { BackendProvider } from './context/BackendContext';
import './App.css';

function App() {
  const { loggedIn, login, register, logout, error, loading } = useAuth();

  return (
    <BackendProvider>
    <BrowserRouter>
      <Routes>
        {/* Public routes */}
        <Route path="/forgot-password" element={<ForgotPasswordPage />} />
        <Route path="/reset-password" element={<ResetPasswordPage />} />
        <Route path="/verify-email" element={<VerifyEmailPage />} />

        {!loggedIn ? (
          <>
            <Route path="/login" element={<LoginPage onLogin={login} error={error} loading={loading} />} />
            <Route path="/register" element={<RegisterPage onRegister={register} error={error} loading={loading} />} />
            <Route path="*" element={<Navigate to="/login" replace />} />
          </>
        ) : (
          <Route element={<Layout onLogout={logout} />}>
            <Route path="/" element={<DashboardPage />} />
            <Route path="/characters/:id" element={<CharacterPage />} />
            <Route path="/account" element={<AccountPage onLogout={logout} />} />
            <Route path="/config" element={<ConfigPage />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Route>
        )}
      </Routes>
    </BrowserRouter>
    </BackendProvider>
  );
}

export default App;
