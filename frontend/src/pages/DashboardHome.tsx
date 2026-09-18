import React, { useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { api } from '../api-client/client';
import { Navbar } from '../components/Navbar';
import { StatusBadge } from '../components/StatusBadge';

export function DashboardHome() {
  const [projects, setProjects] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const navigate = useNavigate();

  useEffect(() => {
    const token = localStorage.getItem('token');
    if (!token) {
      navigate('/login');
      return;
    }
    loadProjects();
  }, []);

  async function loadProjects() {
    try {
      const data = await api('/projects');
      setProjects(data);
    } catch (e: any) {
      if (e.message?.includes('401') || e.message?.includes('token')) {
        navigate('/login');
      }
    } finally {
      setLoading(false);
    }
  }

  const readyProjects = projects.filter(p => p.status === 'ready' && !p.is_stale);
  const staleProjects = projects.filter(p => p.is_stale || p.status === 'stale');
  const indexingProjects = projects.filter(p => ['running', 'pending', 'connecting', 'authenticating', 'branch_discovery', 'cloning', 'scanning', 'parsing', 'domain_analysis', 'functional_analysis', 'workflow_analysis', 'indexing', 'summary_generation', 'quality_check'].includes(p.status));
  const failedProjects = projects.filter(p => p.status === 'failed');

  return (
    <div className="app-layout">
      <Navbar />

      <main className="main-content">
        {/* Top Hero Section */}
        <section style={{ marginBottom: '4rem' }} aria-labelledby="hero-heading">
          <div className="label-caps" style={{ marginBottom: '1rem' }}>
            CODESENSE / SOFTWARE INTELLIGENCE
          </div>

          <h1 id="hero-heading" className="hero-title" style={{ marginBottom: '1.75rem' }}>
            UNDERSTAND<br />
            THE<br />
            <span className="accent">APPLICATION.</span>
          </h1>

          <div className="grid-12">
            <div className="col-8">
              <p style={{ fontSize: '1.25rem', lineHeight: 1.6, color: 'var(--text-secondary)', marginBottom: '2.5rem' }}>
                CodeSense analyzes any software repository and translates implementation details into functional understanding.
                Product Managers and Business Analysts can ask natural-language questions, inspect grounded code evidence,
                trace execution workflows, and evaluate enhancement impact without manually navigating codebases.
              </p>

              <div style={{ display: 'flex', gap: '1rem', flexWrap: 'wrap' }}>
                <Link to="/projects" className="btn btn-primary btn-lg">
                  CONNECT REPOSITORY
                </Link>
                <Link to="/projects" className="btn btn-outline btn-lg">
                  EXPLORE PROJECTS
                </Link>
              </div>
            </div>
          </div>
        </section>

        <hr className="divider-heavy" />

        {/* Dashboard Metrics Section */}
        <section style={{ marginBottom: '4rem' }} aria-labelledby="metrics-heading">
          <div className="label-caps" id="metrics-heading" style={{ marginBottom: '1.25rem' }}>
            PORTFOLIO METRICS
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(170px, 1fr))', gap: '1px', backgroundColor: 'var(--border)', border: '1px solid var(--border)' }}>
            <div className="stat-block">
              <div className="stat-number">{projects.length}</div>
              <div className="stat-label">PROJECTS</div>
            </div>
            <div className="stat-block">
              <div className="stat-number" style={{ color: 'var(--status-ready-text)' }}>{readyProjects.length}</div>
              <div className="stat-label">READY</div>
            </div>
            <div className="stat-block">
              <div className="stat-number" style={{ color: 'var(--status-running-text)' }}>{indexingProjects.length}</div>
              <div className="stat-label">INDEXING</div>
            </div>
            <div className="stat-block">
              <div className="stat-number" style={{ color: 'var(--primary)' }}>{staleProjects.length}</div>
              <div className="stat-label">STALE</div>
            </div>
            <div className="stat-block">
              <div className="stat-number" style={{ color: 'var(--status-failed-text)' }}>{failedProjects.length}</div>
              <div className="stat-label">FAILED</div>
            </div>
          </div>
        </section>

        {/* Recent Connected Projects */}
        <section style={{ marginBottom: '4rem' }} aria-labelledby="recent-projects-heading">
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: '1.25rem' }}>
            <div className="label-caps" id="recent-projects-heading">
              CONNECTED REPOSITORIES
            </div>
            <Link to="/projects" style={{ fontSize: '0.85rem', fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.08em' }}>
              View All Repositories →
            </Link>
          </div>

          {loading ? (
            <div style={{ padding: '2rem', textAlign: 'center', border: '1px solid var(--border)', backgroundColor: 'var(--bg-white)' }}>
              <span className="label-caps">[ LOADING REPOSITORY INDEX… ]</span>
            </div>
          ) : projects.length === 0 ? (
            <div style={{ padding: '3rem 2rem', textAlign: 'center', border: '1px solid var(--border)', backgroundColor: 'var(--bg-white)' }}>
              <h3 style={{ fontSize: '1.25rem', marginBottom: '0.5rem', textTransform: 'uppercase' }}>No Repositories Connected</h3>
              <p style={{ color: 'var(--text-secondary)', marginBottom: '1.5rem' }}>
                Connect a GitHub or GitLab repository to analyze functional workflows and ask arbitrary questions.
              </p>
              <Link to="/projects" className="btn btn-primary">
                CONNECT REPOSITORY
              </Link>
            </div>
          ) : (
            <div style={{ border: '1px solid var(--border)', backgroundColor: 'var(--bg-white)' }}>
              <table className="editorial-table">
                <thead>
                  <tr>
                    <th>PROJECT</th>
                    <th>PROVIDER / URL</th>
                    <th>BRANCH</th>
                    <th>STATUS</th>
                    <th style={{ textAlign: 'right' }}>ACTION</th>
                  </tr>
                </thead>
                <tbody>
                  {projects.slice(0, 6).map((p: any) => {
                    const displayBranch = p.branch || p.default_branch || p.detected_branch || 'main';
                    return (
                      <tr key={p.id}>
                        <td style={{ fontWeight: 700, fontSize: '1rem' }}>
                          <Link to={`/projects/${p.id}`} style={{ color: 'var(--text-primary)', textDecoration: 'none' }}>
                            {p.name}
                          </Link>
                        </td>
                        <td style={{ color: 'var(--text-secondary)', fontSize: '0.85rem' }}>
                          <span style={{ textTransform: 'uppercase', fontWeight: 700, color: 'var(--text-muted)', marginRight: '6px' }}>
                            {p.provider}
                          </span>
                          <span>{p.repo_url.replace('https://github.com/', '').replace('https://gitlab.com/', '')}</span>
                        </td>
                        <td style={{ fontFamily: 'var(--font-mono)', fontSize: '0.825rem', color: 'var(--primary)' }}>
                          {displayBranch}
                        </td>
                        <td>
                          <StatusBadge status={p.status} />
                        </td>
                        <td style={{ textAlign: 'right' }}>
                          <Link to={`/projects/${p.id}`} className="btn btn-outline btn-sm">
                            OPEN WORKSPACE →
                          </Link>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </section>

        <hr className="divider" />

        {/* System Functional Grid: 3 Columns */}
        <section style={{ marginBottom: '4rem' }} aria-labelledby="system-heading">
          <div className="label-caps" id="system-heading" style={{ marginBottom: '1.5rem' }}>
            SYSTEM CAPABILITIES
          </div>

          <div className="grid-12">
            <div className="col-4 stat-block" style={{ backgroundColor: 'var(--bg-white)' }}>
              <div className="label-caps" style={{ color: 'var(--text-muted)', marginBottom: '1rem' }}>
                01 / ARCHITECTURE
              </div>
              <h3 style={{ fontSize: '1.5rem', fontWeight: 900, textTransform: 'uppercase', marginBottom: '0.75rem' }}>
                UNDERSTAND
              </h3>
              <p style={{ color: 'var(--text-secondary)', fontSize: '0.95rem', lineHeight: 1.6 }}>
                Extract and synthesize repository structure, modules, user roles, workflows, data models, and business rules automatically.
              </p>
            </div>

            <div className="col-4 stat-block" style={{ backgroundColor: 'var(--bg-white)' }}>
              <div className="label-caps" style={{ color: 'var(--primary)', marginBottom: '1rem' }}>
                02 / ZERO-HALLUCINATION
              </div>
              <h3 style={{ fontSize: '1.5rem', fontWeight: 900, textTransform: 'uppercase', marginBottom: '0.75rem' }}>
                ASK
              </h3>
              <p style={{ color: 'var(--text-secondary)', fontSize: '0.95rem', lineHeight: 1.6 }}>
                Ask arbitrary natural-language questions about actual application behavior. Every answer is grounded in concrete repository evidence.
              </p>
            </div>

            <div className="col-4 stat-block" style={{ backgroundColor: 'var(--bg-white)' }}>
              <div className="label-caps" style={{ color: 'var(--text-muted)', marginBottom: '1rem' }}>
                03 / EXECUTION GRAPH
              </div>
              <h3 style={{ fontSize: '1.5rem', fontWeight: 900, textTransform: 'uppercase', marginBottom: '0.75rem' }}>
                TRACE
              </h3>
              <p style={{ color: 'var(--text-secondary)', fontSize: '0.95rem', lineHeight: 1.6 }}>
                Follow functionality across frontend entry points, validation gates, backend handlers, data persistence, and external integrations.
              </p>
            </div>
          </div>
        </section>

        <hr className="divider" />

        {/* Why Different Section: Large Typographic List */}
        <section style={{ marginBottom: '4rem' }} aria-labelledby="why-different-heading">
          <div className="label-caps" id="why-different-heading" style={{ marginBottom: '2rem' }}>
            WHY DIFFERENT
          </div>

          <div className="typographic-list">
            <div className="typographic-item">
              <span className="typographic-index">01</span>
              <h3 className="typographic-title">REPOSITORY GROUNDED</h3>
              <p className="typographic-desc">
                Never invents behaviors or hallucinates features. What is in the repository defines reality.
              </p>
            </div>

            <div className="typographic-item">
              <span className="typographic-index">02</span>
              <h3 className="typographic-title">EVIDENCE BACKED</h3>
              <p className="typographic-desc">
                Every claim links directly to source files, symbols, endpoints, and line references.
              </p>
            </div>

            <div className="typographic-item">
              <span className="typographic-index">03</span>
              <h3 className="typographic-title">BUSINESS FRIENDLY</h3>
              <p className="typographic-desc">
                Translates abstract code into clear operational capabilities, validation rules, and user roles for PMs and BAs.
              </p>
            </div>

            <div className="typographic-item">
              <span className="typographic-index">04</span>
              <h3 className="typographic-title">IMPACT AWARE</h3>
              <p className="typographic-desc">
                Evaluates architectural complexity, affected components, and downstream regression risk before writing code.
              </p>
            </div>

            <div className="typographic-item">
              <span className="typographic-index">05</span>
              <h3 className="typographic-title">PROJECT ISOLATED</h3>
              <p className="typographic-desc">
                Strict multi-tenant isolation ensures zero cross-talk, cross-caching, or permission leaks between repositories.
              </p>
            </div>
          </div>
        </section>
      </main>
    </div>
  );
}
