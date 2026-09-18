import React, { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../api-client/client';
import { Navbar } from '../components/Navbar';
import { StatusBadge } from '../components/StatusBadge';

interface ProjectItem {
  id: number;
  name: string;
  repo_url: string;
  provider: string;
  status: string;
  progress: number;
  message: string;
  error?: string;
  configured_branch?: string;
  detected_branch?: string;
  default_branch?: string;
  branch?: string;
  analyzed_commit_sha?: string;
  is_stale?: boolean;
  analysis_health?: any;
  last_synced?: string;
}

export function Projects() {
  const [items, setItems] = useState<ProjectItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showModal, setShowModal] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [resyncingId, setResyncingId] = useState<number | null>(null);

  const [form, setForm] = useState({
    name: '',
    repo_url: '',
    provider: 'github',
    default_branch: '',
    credential: '',
  });

  async function loadProjects() {
    try {
      const data = await api('/projects') as ProjectItem[];
      setItems(data);
      setError(null);
    } catch (err: any) {
      setError(err.message || 'Failed to load projects');
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadProjects();
    const interval = setInterval(() => {
      setItems(prev => {
        const hasActive = prev.some(p =>
          ['running', 'pending', 'connecting', 'authenticating', 'branch_discovery', 'cloning', 'scanning', 'parsing', 'domain_analysis', 'functional_analysis', 'workflow_analysis', 'indexing', 'summary_generation', 'quality_check'].includes(p.status)
        );
        if (hasActive) {
          loadProjects();
        }
        return prev;
      });
    }, 2500);
    return () => clearInterval(interval);
  }, []);

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    if (!form.name.trim() || !form.repo_url.trim()) {
      alert('Please provide project name and repository URL.');
      return;
    }

    if (!form.repo_url.startsWith('http://') && !form.repo_url.startsWith('https://')) {
      alert('Repository URL must begin with http:// or https://');
      return;
    }

    setSubmitting(true);
    try {
      await api('/projects', {
        method: 'POST',
        body: JSON.stringify(form),
      });
      setForm({ name: '', repo_url: '', provider: 'github', default_branch: '', credential: '' });
      setShowModal(false);
      await loadProjects();
    } catch (err: any) {
      alert(`Connection failed: ${err.message}`);
    } finally {
      setSubmitting(false);
    }
  }

  async function handleResync(pid: number, e: React.MouseEvent) {
    e.preventDefault();
    e.stopPropagation();
    setResyncingId(pid);
    try {
      await api(`/projects/${pid}/resync`, { method: 'POST' });
      await loadProjects();
    } catch (err: any) {
      alert(`Resync failed: ${err.message}`);
    } finally {
      setResyncingId(null);
    }
  }

  return (
    <div className="app-layout">
      <Navbar />

      <main className="main-content">
        {/* Header Section */}
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-end', marginBottom: '2.5rem', flexWrap: 'wrap', gap: '1.5rem' }}>
          <div>
            <div className="label-caps" style={{ marginBottom: '0.5rem' }}>
              CONNECTED REPOSITORIES
            </div>
            <h1 className="section-title">
              PROJECTS.
            </h1>
            <p style={{ color: 'var(--text-secondary)', fontSize: '1.1rem', maxWidth: '640px', marginTop: '0.5rem' }}>
              Select a repository to inspect functional architecture, query behaviors, and analyze proposed enhancement impacts.
            </p>
          </div>

          <button
            type="button"
            className="btn btn-primary"
            onClick={() => setShowModal(true)}
          >
            CONNECT REPOSITORY
          </button>
        </div>

        {error && (
          <div
            role="alert"
            style={{
              border: '1px solid var(--status-failed-border)',
              backgroundColor: 'var(--status-failed-bg)',
              color: 'var(--status-failed-text)',
              padding: '1rem',
              fontWeight: 600,
              marginBottom: '2rem',
            }}
          >
            {error}
          </div>
        )}

        {/* Project List / Grid */}
        {loading ? (
          <div style={{ padding: '4rem 2rem', textAlign: 'center', border: '1px solid var(--border)', backgroundColor: 'var(--bg-white)' }}>
            <span className="label-caps">[ LOADING CONNECTED REPOSITORIES… ]</span>
          </div>
        ) : items.length === 0 ? (
          <div style={{ padding: '4rem 2rem', textAlign: 'center', border: '1px solid var(--border)', backgroundColor: 'var(--bg-white)' }}>
            <div className="label-caps" style={{ marginBottom: '0.75rem' }}>NO CONNECTED WORKSPACES</div>
            <h3 style={{ fontSize: '1.75rem', fontWeight: 900, textTransform: 'uppercase', marginBottom: '0.75rem' }}>
              Connect Your First Repository
            </h3>
            <p style={{ color: 'var(--text-secondary)', maxWidth: '480px', margin: '0 auto 2rem' }}>
              Connect a GitHub or GitLab repository to start analyzing business capabilities, user roles, and workflows.
            </p>
            <button
              type="button"
              className="btn btn-primary"
              onClick={() => setShowModal(true)}
            >
              CONNECT REPOSITORY
            </button>
          </div>
        ) : (
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(380px, 1fr))', gap: '1.5rem' }}>
            {items.map(p => {
              const isProcessing = ['running', 'pending', 'connecting', 'cloning', 'parsing', 'analyzing', 'indexing'].includes(p.status);
              const displayBranch = p.branch || p.default_branch || p.detected_branch || p.configured_branch || 'detected';
              const cleanRepoName = p.repo_url.replace('https://github.com/', '').replace('https://gitlab.com/', '');

              return (
                <div
                  key={p.id}
                  className="card card-hover"
                  style={{
                    display: 'flex',
                    flexDirection: 'column',
                    justifyContent: 'space-between',
                    minHeight: '260px',
                  }}
                >
                  <div>
                    {/* Top Meta Line */}
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '1rem' }}>
                      <div className="label-caps" style={{ fontSize: '0.65rem' }}>
                        {p.provider} • ID #{p.id}
                      </div>
                      <StatusBadge status={p.status} />
                    </div>

                    {/* Project Title */}
                    <h2 style={{ fontSize: '1.4rem', fontWeight: 800, textTransform: 'uppercase', marginBottom: '0.35rem' }}>
                      <Link to={`/projects/${p.id}`} className="card-title" style={{ textDecoration: 'none', color: 'inherit' }}>
                        {p.name}
                      </Link>
                    </h2>

                    {/* Repository URL & Branch */}
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '4px', marginBottom: '1.25rem' }}>
                      <span style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', wordBreak: 'break-all' }}>
                        {cleanRepoName}
                      </span>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                        <span className="label-caps" style={{ fontSize: '0.65rem' }}>BRANCH:</span>
                        <span style={{ fontFamily: 'var(--font-mono)', fontSize: '0.8rem', color: 'var(--primary)', fontWeight: 600 }}>
                          {displayBranch}
                        </span>
                      </div>
                      {p.analyzed_commit_sha && (
                        <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                          <span className="label-caps" style={{ fontSize: '0.65rem' }}>COMMIT:</span>
                          <span style={{ fontFamily: 'var(--font-mono)', fontSize: '0.75rem', color: 'var(--text-muted)' }}>
                            {p.analyzed_commit_sha.slice(0, 7)}
                          </span>
                        </div>
                      )}
                    </div>

                    {/* Stale State Representation */}
                    {(p.is_stale || p.status === 'stale') && (
                      <div
                        style={{
                          border: '1px solid var(--primary)',
                          backgroundColor: 'var(--bg-white)',
                          padding: '0.6rem 0.8rem',
                          marginBottom: '1rem',
                          fontSize: '0.8rem',
                        }}
                      >
                        <strong style={{ color: 'var(--primary)' }}>▲ STALE:</strong> Repository changed since last analysis.
                      </div>
                    )}

                    {/* Ingestion Failure Representation */}
                    {p.status === 'failed' && (
                      <div
                        style={{
                          border: '1px solid var(--status-failed-border)',
                          backgroundColor: 'var(--status-failed-bg)',
                          padding: '0.85rem',
                          marginBottom: '1rem',
                        }}
                      >
                        <div className="label-caps" style={{ color: 'var(--status-failed-text)', marginBottom: '4px' }}>
                          FAILED / INGESTION FAILED
                        </div>
                        <p style={{ color: 'var(--status-failed-text)', fontSize: '0.85rem', fontWeight: 600, margin: 0 }}>
                          {p.error || p.message || 'Clone or repository parsing failed.'}
                        </p>
                        {p.error && p.error.length > 80 && (
                          <details style={{ marginTop: '0.5rem', fontSize: '0.75rem' }}>
                            <summary style={{ cursor: 'pointer', color: 'var(--status-failed-text)', fontWeight: 700 }}>
                              [ TECHNICAL ERROR DETAILS ]
                            </summary>
                            <pre style={{ marginTop: '4px', padding: '6px', background: '#141414', color: '#E3E2DE', overflowX: 'auto', whiteSpace: 'pre-wrap', fontFamily: 'var(--font-mono)' }}>
                              {p.error}
                            </pre>
                          </details>
                        )}
                      </div>
                    )}

                    {/* Processing Representation */}
                    {isProcessing && (
                      <div style={{ border: '1px solid var(--border)', backgroundColor: 'var(--bg-white)', padding: '0.75rem', marginBottom: '1rem' }}>
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '4px' }}>
                          <span className="label-caps" style={{ color: 'var(--status-running-text)' }}>
                            STATUS: {p.status.toUpperCase()}
                          </span>
                          <span style={{ fontFamily: 'var(--font-mono)', fontSize: '0.75rem', fontWeight: 700 }}>
                            {p.progress || 0}%
                          </span>
                        </div>
                        <p style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', margin: 0 }}>
                          {p.message || 'Processing repository structure and extracting knowledge chunks…'}
                        </p>
                      </div>
                    )}

                    {p.status === 'ready' && (
                      <p style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', marginBottom: '1rem' }}>
                        {p.message || 'Repository fully indexed and ready for functional Q&A and workflow tracing.'}
                      </p>
                    )}
                  </div>

                  {/* Bottom Action Footer */}
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderTop: '1px solid var(--border)', paddingTop: '1rem', marginTop: '1rem' }}>
                    <button
                      type="button"
                      className="btn btn-tertiary"
                      style={{ padding: 0 }}
                      onClick={e => handleResync(p.id, e)}
                      disabled={resyncingId === p.id || isProcessing}
                    >
                      {resyncingId === p.id ? 'RESYNCING…' : p.status === 'failed' ? 'RETRY / RESYNC' : 'RESYNC'}
                    </button>

                    <Link to={`/projects/${p.id}`} className="btn btn-outline btn-sm">
                      OPEN WORKSPACE →
                    </Link>
                  </div>
                </div>
              );
            })}
          </div>
        )}

        {/* Connect Repository Modal */}
        {showModal && (
          <div className="modal-overlay" onClick={() => !submitting && setShowModal(false)} role="dialog" aria-modal="true">
            <div className="modal-panel" onClick={e => e.stopPropagation()}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '2rem' }}>
                <div>
                  <div className="label-caps" style={{ marginBottom: '0.25rem' }}>
                    REPOSITORY ONBOARDING
                  </div>
                  <h2 style={{ fontSize: '1.75rem', fontWeight: 900, textTransform: 'uppercase' }}>
                    CONNECT REPOSITORY.
                  </h2>
                </div>
                <button
                  type="button"
                  onClick={() => setShowModal(false)}
                  style={{ background: 'transparent', border: 'none', fontSize: '1.5rem', cursor: 'pointer', padding: '0 0.5rem', color: 'var(--text-primary)' }}
                  aria-label="Close modal"
                >
                  ✕
                </button>
              </div>

              <form onSubmit={handleCreate} style={{ display: 'flex', flexDirection: 'column', gap: '1.25rem' }}>
                <div className="form-group" style={{ margin: 0 }}>
                  <label htmlFor="repoProvider" className="form-label">
                    REPOSITORY PROVIDER
                  </label>
                  <select
                    id="repoProvider"
                    className="select"
                    value={form.provider}
                    onChange={e => setForm({ ...form, provider: e.target.value })}
                  >
                    <option value="github">GitHub</option>
                    <option value="gitlab">GitLab</option>
                  </select>
                </div>

                <div className="form-group" style={{ margin: 0 }}>
                  <label htmlFor="projectName" className="form-label">
                    PROJECT / APPLICATION NAME
                  </label>
                  <input
                    id="projectName"
                    type="text"
                    className="form-input"
                    placeholder="e.g. Alphalens Factor Analysis"
                    value={form.name}
                    onChange={e => setForm({ ...form, name: e.target.value })}
                    required
                  />
                </div>

                <div className="form-group" style={{ margin: 0 }}>
                  <label htmlFor="repoUrl" className="form-label">
                    REPOSITORY CLONE URL (HTTPS)
                  </label>
                  <input
                    id="repoUrl"
                    type="url"
                    className="form-input"
                    placeholder="https://github.com/organization/repository"
                    value={form.repo_url}
                    onChange={e => setForm({ ...form, repo_url: e.target.value })}
                    required
                  />
                </div>

                <div className="form-group" style={{ margin: 0 }}>
                  <label htmlFor="repoBranch" className="form-label">
                    BRANCH (OPTIONAL)
                  </label>
                  <input
                    id="repoBranch"
                    type="text"
                    className="form-input"
                    placeholder="Leave empty for automatic detection"
                    value={form.default_branch}
                    onChange={e => setForm({ ...form, default_branch: e.target.value })}
                  />
                  <span style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', marginTop: '4px' }}>
                    {form.default_branch.trim()
                      ? `Using branch: ${form.default_branch.trim()}`
                      : 'Default branch will be detected automatically.'}
                  </span>
                </div>

                <div className="form-group" style={{ margin: 0 }}>
                  <label htmlFor="repoToken" className="form-label">
                    ACCESS TOKEN / CREDENTIALS (FOR PRIVATE REPOSITORIES)
                  </label>
                  <input
                    id="repoToken"
                    type="password"
                    className="form-input"
                    placeholder="Personal Access Token (optional for public repos)"
                    value={form.credential}
                    onChange={e => setForm({ ...form, credential: e.target.value })}
                  />
                  <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)', marginTop: '4px' }}>
                    Credentials are encrypted in transit and never exposed to unauthenticated users or normal UI views.
                  </span>
                </div>

                <div style={{ display: 'flex', gap: '1rem', marginTop: '1rem', justifyContent: 'flex-end' }}>
                  <button
                    type="button"
                    className="btn btn-outline"
                    onClick={() => setShowModal(false)}
                    disabled={submitting}
                  >
                    CANCEL
                  </button>
                  <button
                    type="submit"
                    className="btn btn-primary"
                    disabled={submitting}
                  >
                    {submitting ? 'CONNECTING…' : 'CONNECT REPOSITORY'}
                  </button>
                </div>
              </form>
            </div>
          </div>
        )}
      </main>
    </div>
  );
}
