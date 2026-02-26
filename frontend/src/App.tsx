import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { useAuth } from './hooks/useAuth';
import { Layout } from './components/Layout';
import { LoginPage } from './pages/LoginPage';
import { RegisterPage } from './pages/RegisterPage';
import { DashboardPage } from './pages/DashboardPage';
import { CharacterPage } from './pages/CharacterPage';
import './App.css';

function App() {
  const { loggedIn, login, register, logout, error, loading } = useAuth();

  return (
    <BrowserRouter>
      <Routes>
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
            <Route path="*" element={<Navigate to="/" replace />} />
          </Route>
        )}
      </Routes>
    </BrowserRouter>
  );
}

export default App;
