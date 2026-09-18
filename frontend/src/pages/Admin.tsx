import React, { useEffect, useState } from 'react';
import { api, getUser } from '../api-client/client';
import { Navbar } from '../components/Navbar';

interface UserItem {
  id: number;
  email: string;
  name: string;
  role: string;
  projects?: Array<{
    project_id: number;
    project_name: string;
    access_level: string;
  }>;
}

interface ProjectOption {
  id: number;
  name: string;
}

export function Admin() {
  const currentUser = getUser();
  const [users, setUsers] = useState<UserItem[]>([]);
  const [projects, setProjects] = useState<ProjectOption[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Grant form state
  const [grantUid, setGrantUid] = useState<number | ''>('');
  const [grantPid, setGrantPid] = useState<number | ''>('');
  const [grantLevel, setGrantLevel] = useState('viewer');
  const [submitting, setSubmitting] = useState(false);

  async function loadData() {
    try {
      const [uData, pData] = await Promise.all([
        api('/admin/users') as Promise<UserItem[]>,
        api('/projects') as Promise<ProjectOption[]>,
      ]);
      setUsers(uData);
      setProjects(pData);
      if (uData.length > 0 && grantUid === '') setGrantUid(uData[0].id);
      if (pData.length > 0 && grantPid === '') setGrantPid(pData[0].id);
    } catch (err: any) {
      setError(err.message || 'Failed to load administrative data');
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadData();
  }, []);

  async function handleGrant(e: React.FormEvent) {
    e.preventDefault();
    if (!grantUid || !grantPid) return;
    setSubmitting(true);
    try {
      await api(`/admin/users/${grantUid}/projects`, {
        method: 'POST',
        body: JSON.stringify({
          project_id: Number(grantPid),
          access_level: grantLevel,
        }),
      });
      await loadData();
      alert('Access permissions granted.');
    } catch (err: any) {
      alert(`Grant failed: ${err.message}`);
    } finally {
      setSubmitting(false);
    }
  }

  async function handleRevoke(uid: number, pid: number) {
    if (!confirm('Revoke access for this user to the selected project?')) return;
    try {
      await api(`/admin/users/${uid}/projects/${pid}`, {
        method: 'DELETE',
      });
      await loadData();
    } catch (err: any) {
      alert(`Revoke failed: ${err.message}`);
    }
  }

  if (currentUser?.role !== 'admin') {
    return (
      <div className="app-layout">
        <Navbar />
        <main className="main-content">
          <div
            role="alert"
            style={{
              border: '2px solid var(--status-failed-border)',
              backgroundColor: 'var(--status-failed-bg)',
              padding: '4rem 2rem',
              textAlign: 'center',
              margin: '3rem auto',
              maxWidth: '600px',
            }}
          >
            <div className="label-caps" style={{ color: 'var(--status-failed-text)', marginBottom: '0.5rem' }}>
              SECURITY / AUTHORIZATION GATE
            </div>
            <h1 style={{ fontSize: '2.5rem', fontWeight: 900, textTransform: 'uppercase', color: 'var(--status-failed-text)', marginBottom: '1rem' }}>
              ACCESS DENIED.
            </h1>
            <p style={{ color: 'var(--status-failed-text)', fontSize: '1rem', lineHeight: 1.5, margin: 0 }}>
              Administrator credentials are required to view and manage enterprise user assignments and project isolation.
            </p>
          </div>
        </main>
      </div>
    );
  }

  return (
    <div className="app-layout">
      <Navbar />

      <main className="main-content">
        {/* Header */}
        <section style={{ marginBottom: '3rem' }}>
          <div className="label-caps" style={{ marginBottom: '0.25rem' }}>
            ENTERPRISE ADMINISTRATION
          </div>
          <h1 className="section-title" style={{ marginBottom: '0.5rem' }}>
            ACCESS CONTROL.
          </h1>
          <p style={{ color: 'var(--text-secondary)', fontSize: '1.1rem', maxWidth: '680px' }}>
            Manage user roles, grant repository workspace memberships, and enforce tenant access isolation.
          </p>
        </section>

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

        {/* Form and Hierarchy: 12-Column Grid */}
        <div className="grid-12" style={{ marginBottom: '3rem' }}>
          {/* Form: Cols 1-7 */}
          <div className="col-8" style={{ border: '2px solid var(--text-primary)', backgroundColor: 'var(--bg-white)', padding: '2rem' }}>
            <div className="label-caps" style={{ marginBottom: '0.5rem' }}>
              GRANT / REASSIGN ACCESS
            </div>
            <h3 style={{ fontSize: '1.5rem', fontWeight: 900, textTransform: 'uppercase', marginBottom: '1.5rem' }}>
              ASSIGN PROJECT ACCESS.
            </h3>

            <form onSubmit={handleGrant} style={{ display: 'flex', flexDirection: 'column', gap: '1.25rem' }}>
              <div className="form-group" style={{ margin: 0 }}>
                <label htmlFor="selectUser" className="form-label">
                  SELECT USER
                </label>
                <select
                  id="selectUser"
                  className="select"
                  value={grantUid}
                  onChange={e => setGrantUid(Number(e.target.value))}
                >
                  {users.map(u => (
                    <option key={u.id} value={u.id}>
                      {u.email} ({u.role.toUpperCase()})
                    </option>
                  ))}
                </select>
              </div>

              <div className="form-group" style={{ margin: 0 }}>
                <label htmlFor="selectProject" className="form-label">
                  SELECT REPOSITORY / PROJECT
                </label>
                <select
                  id="selectProject"
                  className="select"
                  value={grantPid}
                  onChange={e => setGrantPid(Number(e.target.value))}
                >
                  {projects.map(p => (
                    <option key={p.id} value={p.id}>
                      #{p.id} — {p.name}
                    </option>
                  ))}
                </select>
              </div>

              <div className="form-group" style={{ margin: 0 }}>
                <label htmlFor="selectLevel" className="form-label">
                  PERMISSION TIER
                </label>
                <select
                  id="selectLevel"
                  className="select"
                  value={grantLevel}
                  onChange={e => setGrantLevel(e.target.value)}
                >
                  <option value="viewer">Viewer (Read-only Overview & Q&A)</option>
                  <option value="contributor">Contributor (Q&A, Trace, Resync & Docs)</option>
                  <option value="owner">Owner (Full Workspace Administration)</option>
                </select>
              </div>

              <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: '0.5rem' }}>
                <button
                  type="submit"
                  className="btn btn-primary"
                  disabled={submitting}
                >
                  {submitting ? 'SAVING PERMISSIONS…' : 'GRANT / UPDATE ACCESS'}
                </button>
              </div>
            </form>
          </div>

          {/* Access Hierarchy: Cols 8-12 */}
          <div className="col-4 stat-block" style={{ backgroundColor: 'var(--bg-white)', padding: '2rem' }}>
            <div className="label-caps" style={{ marginBottom: '0.5rem' }}>
              PERMISSION TIERS
            </div>
            <h4 style={{ fontSize: '1.25rem', fontWeight: 900, textTransform: 'uppercase', marginBottom: '1.25rem' }}>
              ACCESS HIERARCHY
            </h4>

            <div style={{ display: 'flex', flexDirection: 'column', gap: '1.25rem', fontSize: '0.85rem' }}>
              <div>
                <strong style={{ textTransform: 'uppercase', color: 'var(--text-primary)', display: 'block', marginBottom: '2px' }}>
                  OWNER
                </strong>
                <span style={{ color: 'var(--text-secondary)' }}>
                  Full authority to run queries, trace flows, trigger resyncs, generate documents, and modify settings.
                </span>
              </div>
              <div style={{ borderTop: '1px solid var(--border)', paddingTop: '1rem' }}>
                <strong style={{ textTransform: 'uppercase', color: 'var(--text-primary)', display: 'block', marginBottom: '2px' }}>
                  CONTRIBUTOR
                </strong>
                <span style={{ color: 'var(--text-secondary)' }}>
                  Authorized to run functional queries, inspect trace execution graphs, and export DOCX/PDF reports.
                </span>
              </div>
              <div style={{ borderTop: '1px solid var(--border)', paddingTop: '1rem' }}>
                <strong style={{ textTransform: 'uppercase', color: 'var(--text-primary)', display: 'block', marginBottom: '2px' }}>
                  VIEWER
                </strong>
                <span style={{ color: 'var(--text-secondary)' }}>
                  Read-only access to briefing document summaries and basic functional Q&A.
                </span>
              </div>
            </div>
          </div>
        </div>

        {/* Users Table */}
        <section aria-labelledby="users-table-heading">
          <div className="label-caps" id="users-table-heading" style={{ marginBottom: '1rem' }}>
            REGISTERED USERS & PROJECT ASSIGNMENTS
          </div>

          {loading ? (
            <div style={{ padding: '3rem', textAlign: 'center', border: '1px solid var(--border)', backgroundColor: 'var(--bg-white)' }}>
              <span className="label-caps">[ LOADING USER DIRECTORY… ]</span>
            </div>
          ) : (
            <div style={{ border: '1px solid var(--border)', backgroundColor: 'var(--bg-white)' }}>
              <table className="editorial-table">
                <thead>
                  <tr>
                    <th>USER ID</th>
                    <th>EMAIL ADDRESS</th>
                    <th>GLOBAL ROLE</th>
                    <th>ASSIGNED PROJECTS & PERMISSIONS</th>
                  </tr>
                </thead>
                <tbody>
                  {users.map(u => (
                    <tr key={u.id}>
                      <td style={{ fontFamily: 'var(--font-mono)', fontWeight: 700, color: 'var(--text-muted)' }}>
                        #{u.id}
                      </td>
                      <td style={{ fontWeight: 700, fontSize: '0.95rem' }}>
                        {u.email}
                      </td>
                      <td>
                        <span
                          style={{
                            fontFamily: 'var(--font-mono)',
                            fontSize: '0.75rem',
                            fontWeight: 700,
                            textTransform: 'uppercase',
                            padding: '2px 6px',
                            border: '1px solid var(--text-primary)',
                            backgroundColor: u.role === 'admin' ? 'var(--text-primary)' : 'var(--bg-base)',
                            color: u.role === 'admin' ? 'var(--bg-base)' : 'var(--text-primary)',
                          }}
                        >
                          {u.role}
                        </span>
                      </td>
                      <td>
                        {u.projects && u.projects.length > 0 ? (
                          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.5rem' }}>
                            {u.projects.map((proj, idx) => (
                              <span
                                key={idx}
                                style={{
                                  border: '1px solid var(--border)',
                                  backgroundColor: 'var(--bg-base)',
                                  padding: '4px 8px',
                                  fontSize: '0.8rem',
                                  display: 'inline-flex',
                                  alignItems: 'center',
                                  gap: '8px',
                                }}
                              >
                                <strong>{proj.project_name}</strong>
                                <span style={{ color: 'var(--primary)', fontFamily: 'var(--font-mono)', fontSize: '0.75rem' }}>
                                  [{proj.access_level.toUpperCase()}]
                                </span>
                                <button
                                  type="button"
                                  onClick={() => handleRevoke(u.id, proj.project_id)}
                                  style={{
                                    background: 'transparent',
                                    border: 'none',
                                    color: 'var(--status-failed-text)',
                                    cursor: 'pointer',
                                    fontWeight: 900,
                                    padding: '0 2px',
                                    lineHeight: 1,
                                  }}
                                  title="Revoke access"
                                  aria-label={`Revoke access to ${proj.project_name}`}
                                >
                                  ✕
                                </button>
                              </span>
                            ))}
                          </div>
                        ) : (
                          <span style={{ color: 'var(--text-muted)', fontSize: '0.85rem' }}>
                            {u.role === 'admin' ? 'All projects (Enterprise Admin)' : 'No projects mapped'}
                          </span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      </main>
    </div>
  );
}
