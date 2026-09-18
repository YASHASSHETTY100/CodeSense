import React, { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { api, setSession } from '../api-client/client';

export function Login() {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const nav = useNavigate();

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!email.trim() || !password) {
      setError('Please provide your email address and password.');
      return;
    }

    setLoading(true);
    setError(null);

    try {
      const res = await api('/auth/login', {
        method: 'POST',
        body: JSON.stringify({ email: email.trim(), password }),
      }) as any;

      const userObj = {
        email: res.email || email.trim(),
        role: res.role || 'pm',
        name: res.name || email.split('@')[0],
      };

      setSession(res.token, userObj);
      nav('/dashboard');
    } catch (err: any) {
      setError(err.message || 'Invalid email or password.');
    } finally {
      setLoading(false);
    }
  }

  return (
    <div
      style={{
        minHeight: '100vh',
        backgroundColor: 'var(--bg-base)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        padding: '2rem 1.5rem',
      }}
    >
      <div
        style={{
          maxWidth: '480px',
          width: '100%',
          border: '2px solid var(--text-primary)',
          backgroundColor: 'var(--bg-base)',
          padding: '3rem 2.5rem',
        }}
      >
        {/* Brand Header */}
        <div style={{ marginBottom: '2.5rem' }}>
          <div className="label-caps" style={{ marginBottom: '0.5rem' }}>
            CODESENSE / AUTHENTICATION
          </div>
          <h1
            style={{
              fontSize: '2.75rem',
              fontWeight: 900,
              textTransform: 'uppercase',
              letterSpacing: '-0.03em',
              lineHeight: 0.95,
              marginBottom: '0.75rem',
            }}
          >
            SIGN IN.
          </h1>
          <p style={{ color: 'var(--text-secondary)', fontSize: '0.95rem' }}>
            Enter your credentials to access your functional application workspaces.
          </p>
        </div>

        {error && (
          <div
            role="alert"
            style={{
              border: '1px solid var(--status-failed-border)',
              backgroundColor: 'var(--status-failed-bg)',
              color: 'var(--status-failed-text)',
              padding: '0.75rem 1rem',
              fontSize: '0.85rem',
              fontWeight: 600,
              marginBottom: '1.5rem',
            }}
          >
            {error}
          </div>
        )}

        <form onSubmit={handleSubmit} style={{ display: 'flex', flexDirection: 'column', gap: '1.25rem' }}>
          <div className="form-group" style={{ margin: 0 }}>
            <label htmlFor="email" className="form-label">
              EMAIL ADDRESS
            </label>
            <input
              id="email"
              type="email"
              className="form-input"
              placeholder="user@enterprise.com"
              value={email}
              onChange={e => setEmail(e.target.value)}
              required
              autoFocus
            />
          </div>

          <div className="form-group" style={{ margin: 0 }}>
            <label htmlFor="password" className="form-label">
              PASSWORD
            </label>
            <input
              id="password"
              type="password"
              className="form-input"
              placeholder="••••••••••••"
              value={password}
              onChange={e => setPassword(e.target.value)}
              required
            />
          </div>

          <button
            type="submit"
            className="btn btn-primary btn-lg"
            disabled={loading}
            style={{ marginTop: '0.5rem', width: '100%' }}
          >
            {loading ? 'AUTHENTICATING…' : 'SIGN IN'}
          </button>
        </form>

        <div style={{ marginTop: '2rem', borderTop: '1px solid var(--border)', paddingTop: '1.5rem', textAlign: 'center' }}>
          <p style={{ fontSize: '0.875rem', color: 'var(--text-secondary)' }}>
            Need workspace access?{' '}
            <Link to="/signup" style={{ color: 'var(--primary)', fontWeight: 700 }}>
              CREATE ACCOUNT
            </Link>
          </p>
        </div>
      </div>
    </div>
  );
}
