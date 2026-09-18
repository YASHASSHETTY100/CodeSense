import React, { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { api } from '../api-client/client';

export function Signup() {
  const [name, setName] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);
  const nav = useNavigate();

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setSuccessMsg(null);

    // Frontend validations
    if (!name.trim()) {
      setError('Please enter your full name.');
      return;
    }
    if (!email.trim() || !email.includes('@') || !email.includes('.')) {
      setError('Please enter a valid work email address.');
      return;
    }
    if (password.length < 8) {
      setError('Password must be at least 8 characters long.');
      return;
    }
    if (password !== confirmPassword) {
      setError('Passwords do not match. Please re-enter your password.');
      return;
    }

    setLoading(true);
    try {
      await api('/auth/signup', {
        method: 'POST',
        body: JSON.stringify({
          name: name.trim(),
          email: email.trim(),
          password,
          confirm_password: confirmPassword,
        }),
      });

      setSuccessMsg('Account created. Please sign in.');
      setTimeout(() => {
        nav('/login');
      }, 1500);
    } catch (err: any) {
      setError(err.message || 'Signup failed. Please check your details.');
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
          maxWidth: '520px',
          width: '100%',
          border: '2px solid var(--text-primary)',
          backgroundColor: 'var(--bg-base)',
          padding: '3rem 2.5rem',
        }}
      >
        <div style={{ marginBottom: '2.5rem' }}>
          <div className="label-caps" style={{ marginBottom: '0.5rem' }}>
            CODESENSE / ONBOARDING
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
            CREATE ACCOUNT.
          </h1>
          <p style={{ color: 'var(--text-secondary)', fontSize: '0.95rem' }}>
            Set up your analyst credentials to query repositories and trace application logic.
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

        {successMsg && (
          <div
            role="status"
            style={{
              border: '1px solid var(--status-ready-border)',
              backgroundColor: 'var(--status-ready-bg)',
              color: 'var(--status-ready-text)',
              padding: '0.75rem 1rem',
              fontSize: '0.85rem',
              fontWeight: 700,
              textTransform: 'uppercase',
              letterSpacing: '0.05em',
              marginBottom: '1.5rem',
            }}
          >
            ✓ {successMsg}
          </div>
        )}

        <form onSubmit={handleSubmit} style={{ display: 'flex', flexDirection: 'column', gap: '1.25rem' }}>
          <div className="form-group" style={{ margin: 0 }}>
            <label htmlFor="fullName" className="form-label">
              FULL NAME
            </label>
            <input
              id="fullName"
              type="text"
              className="form-input"
              placeholder="e.g. Alex Vance"
              value={name}
              onChange={e => setName(e.target.value)}
              required
              autoFocus
            />
          </div>

          <div className="form-group" style={{ margin: 0 }}>
            <label htmlFor="email" className="form-label">
              WORK EMAIL ADDRESS
            </label>
            <input
              id="email"
              type="email"
              className="form-input"
              placeholder="alex@enterprise.com"
              value={email}
              onChange={e => setEmail(e.target.value)}
              required
            />
          </div>

          <div className="form-group" style={{ margin: 0 }}>
            <label htmlFor="password" className="form-label">
              PASSWORD (MINIMUM 8 CHARACTERS)
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

          <div className="form-group" style={{ margin: 0 }}>
            <label htmlFor="confirmPassword" className="form-label">
              CONFIRM PASSWORD
            </label>
            <input
              id="confirmPassword"
              type="password"
              className="form-input"
              placeholder="••••••••••••"
              value={confirmPassword}
              onChange={e => setConfirmPassword(e.target.value)}
              required
            />
          </div>

          <button
            type="submit"
            className="btn btn-primary btn-lg"
            disabled={loading}
            style={{ marginTop: '0.5rem', width: '100%' }}
          >
            {loading ? 'CREATING ACCOUNT…' : 'CREATE ACCOUNT'}
          </button>
        </form>

        <div style={{ marginTop: '2rem', borderTop: '1px solid var(--border)', paddingTop: '1.5rem', textAlign: 'center' }}>
          <p style={{ fontSize: '0.875rem', color: 'var(--text-secondary)' }}>
            Already have an account?{' '}
            <Link to="/login" style={{ color: 'var(--primary)', fontWeight: 700 }}>
              SIGN IN
            </Link>
          </p>
        </div>
      </div>
    </div>
  );
}
