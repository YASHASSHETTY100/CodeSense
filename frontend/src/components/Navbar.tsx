import React from 'react';
import { Link, useLocation } from 'react-router-dom';
import { getUser, logout } from '../api-client/client';

interface NavbarProps {
  projectContext?: {
    name?: string;
    branch?: string;
    status?: string;
  };
}

export function Navbar({ projectContext }: NavbarProps) {
  const user = getUser();
  const location = useLocation();

  return (
    <header className="navbar" role="banner">
      <div className="navbar-inner">
        {/* Cols 1-3: Brand */}
        <Link to="/dashboard" className="navbar-brand" aria-label="CodeSense Home">
          <span className="navbar-brand-text">CODESENSE</span>
          <span className="navbar-brand-tag">INTELLIGENCE</span>
        </Link>

        {/* Cols 4-8/9: Context */}
        <div className="navbar-context">
          {projectContext?.name ? (
            <>
              <span style={{ fontWeight: 700, color: 'var(--text-primary)' }}>
                {projectContext.name}
              </span>
              {projectContext.branch && (
                <>
                  <span style={{ color: 'var(--border)' }}>/</span>
                  <span style={{ fontFamily: 'var(--font-mono)', color: 'var(--primary)', fontSize: '0.8rem' }}>
                    {projectContext.branch}
                  </span>
                </>
              )}
            </>
          ) : (
            <span style={{ color: 'var(--text-muted)', fontSize: '0.75rem', letterSpacing: '0.1em', textTransform: 'uppercase' }}>
              Reality-First Software Intelligence
            </span>
          )}
        </div>

        {/* Cols 10-12: Nav Links & User */}
        <nav className="navbar-links" aria-label="Main Navigation">
          <Link
            to="/dashboard"
            className={`nav-link ${location.pathname === '/dashboard' ? 'active' : ''}`}
          >
            Dashboard
          </Link>
          <Link
            to="/projects"
            className={`nav-link ${location.pathname === '/projects' ? 'active' : ''}`}
          >
            Projects
          </Link>
          {user?.role === 'admin' && (
            <Link
              to="/admin"
              className={`nav-link ${location.pathname === '/admin' ? 'active' : ''}`}
            >
              Admin
            </Link>
          )}

          {user && (
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', marginLeft: '0.5rem' }}>
              <span
                style={{
                  fontSize: '0.75rem',
                  fontFamily: 'var(--font-mono)',
                  color: 'var(--text-muted)',
                  border: '1px solid var(--border)',
                  padding: '4px 8px',
                  lineHeight: 1,
                }}
                title={user.email}
              >
                {user.email.split('@')[0]} [{user.role.toUpperCase()}]
              </span>
              <button
                type="button"
                onClick={logout}
                className="btn btn-outline btn-sm"
                aria-label="Sign out"
              >
                Logout
              </button>
            </div>
          )}
        </nav>
      </div>
    </header>
  );
}
