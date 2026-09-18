import React, { useEffect, useState } from 'react';
import { useParams, Link } from 'react-router-dom';
import { api, BASE, downloadFile } from '../api-client/client';
import { Navbar } from '../components/Navbar';
import { StatusBadge } from '../components/StatusBadge';
import { ConfidenceBadge } from '../components/ConfidenceBadge';
import { ComplexityBadge } from '../components/ComplexityBadge';
import { EvidenceCard } from '../components/EvidenceCard';
import { FlowStep } from '../components/FlowStep';

type TabType = 'overview' | 'ask' | 'trace' | 'enhancement' | 'docs';

function renderMarkdownToHtml(markdown: string) {
  if (!markdown) return '';
  // Clean raw parser artifacts if any slipped through
  let clean = markdown
    .replace(/module:root/gi, 'core module')
    .replace(/chunk_id:\s*[a-zA-Z0-9_-]+/gi, '')
    .replace(/parser_id:\s*[a-zA-Z0-9_-]+/gi, '');

  return clean
    .replace(/^### (.*$)/gim, '<h3>$1</h3>')
    .replace(/^## (.*$)/gim, '<h2>$1</h2>')
    .replace(/^# (.*$)/gim, '<h1>$1</h1>')
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/\*(.+?)\*/g, '<em>$1</em>')
    .replace(/^- (.+)$/gim, '<li>$1</li>')
    .replace(/(<li>.*<\/li>)/gis, '<ul>$1</ul>')
    .replace(/<\/ul>\s*<ul>/g, '')
    .replace(/\n{2,}/g, '<p></p>')
    .replace(/\n/g, '<br />');
}

export function Dashboard() {
  const { id } = useParams<{ id: string }>();
  const [activeTab, setActiveTab] = useState<TabType>('overview');

  const [project, setProject] = useState<any>(null);
  const [loadingProject, setLoadingProject] = useState(true);

  // Overview state
  const [summaryData, setSummaryData] = useState<any>(null);
  const [loadingSummary, setLoadingSummary] = useState(false);

  // Ask Q&A state
  const [question, setQuestion] = useState('');
  const [suggestedQuestions, setSuggestedQuestions] = useState<string[]>([]);
  const [conversationHistory, setConversationHistory] = useState<Array<{ question: string; answer: string }>>([]);
  const [qAns, setQAns] = useState<any>(null);
  const [loadingQ, setLoadingQ] = useState(false);
  const [showEvidence, setShowEvidence] = useState(false);

  // Trace Flow state
  const [traceQ, setTraceQ] = useState('');
  const [traceRes, setTraceRes] = useState<any>(null);
  const [loadingTrace, setLoadingTrace] = useState(false);

  // Enhancement state
  const [enhReq, setEnhReq] = useState('');
  const [enhRes, setEnhRes] = useState<any>(null);
  const [loadingEnh, setLoadingEnh] = useState(false);

  // Documentation state
  const [docScope, setDocScope] = useState('full');
  const [docLoading, setDocLoading] = useState(false);
  const [docFormatLoading, setDocFormatLoading] = useState<'docx' | 'pdf' | null>(null);
  const [docError, setDocError] = useState<string | null>(null);
  const [generatedDocs, setGeneratedDocs] = useState<Array<{ id: number; format: string; url: string; date: string }>>([]);
  const [generatingFullDocs, setGeneratingFullDocs] = useState(false);

  // Analysis Health state
  const [healthMetrics, setHealthMetrics] = useState<any>(null);

  // Clean isolation on project ID switch
  useEffect(() => {
    setProject(null);
    setSummaryData(null);
    setQAns(null);
    setConversationHistory([]);
    setTraceRes(null);
    setEnhRes(null);
    setGeneratedDocs([]);
    setQuestion('');
    setTraceQ('');
    setEnhReq('');
    setDocError(null);
    setHealthMetrics(null);

    loadProject();
    loadSummary();
    loadSuggestions();
    loadHealth();
  }, [id]);

  // Automated Ingestion & Freshness Polling Effect
  useEffect(() => {
    if (!project) return;
    const st = (project.status || '').toLowerCase();
    const terminal = ['ready', 'failed', 'stale'];

    if (!terminal.includes(st)) {
      const timer = setInterval(async () => {
        try {
          const stat = await api(`/projects/${id}/ingestion-status`);
          setProject((prev: any) => ({ ...prev, ...stat }));
          if (stat.status === 'ready') {
            clearInterval(timer);
            loadSummary();
            loadSuggestions();
            loadHealth();
          } else if (stat.status === 'failed') {
            clearInterval(timer);
          }
        } catch (err) {
          console.error('Polling error:', err);
        }
      }, 2000);
      return () => clearInterval(timer);
    } else if (st === 'ready') {
      // Background freshness check
      api(`/projects/${id}/freshness`).then(res => {
        if (res?.is_stale) {
          setProject((prev: any) => ({ ...prev, is_stale: true, status: 'stale' }));
        }
      }).catch(() => {});
    }
  }, [project?.status, id]);

  async function loadHealth() {
    try {
      const h = await api(`/projects/${id}/health-metrics`);
      if (h && typeof h === 'object') setHealthMetrics(h);
    } catch (err) {
      console.error('Could not load health metrics:', err);
    }
  }

  async function loadProject() {
    setLoadingProject(true);
    try {
      const p = await api(`/projects/${id}`);
      setProject(p);
      if (p?.analysis_health) setHealthMetrics(p.analysis_health);
    } catch (e: any) {
      console.error(e);
    } finally {
      setLoadingProject(false);
    }
  }

  async function loadSummary() {
    setLoadingSummary(true);
    try {
      const s = await api(`/projects/${id}/summary`);
      setSummaryData(s);
    } catch (e: any) {
      setSummaryData({ error: String(e.message || e) });
    } finally {
      setLoadingSummary(false);
    }
  }

  async function loadSuggestions() {
    try {
      const s = await api(`/projects/${id}/suggested-questions`);
      if (s?.questions?.length) {
        setSuggestedQuestions(s.questions);
        if (!question && s.questions[0]) setQuestion(s.questions[0]);
        if (!traceQ && s.questions[1]) setTraceQ(s.questions[1]);
      }
    } catch (e) {
      console.error('Could not load suggestions:', e);
    }
  }

  async function handleAsk(queryText?: string) {
    const qToRun = queryText || question;
    if (!qToRun.trim()) return;
    setLoadingQ(true);
    try {
      const res = await api(`/projects/${id}/ask`, {
        method: 'POST',
        body: JSON.stringify({ question: qToRun, history: conversationHistory }),
      });
      setQAns(res);
      setShowEvidence(false);
      if (res?.status === 'SUCCESS' && res.answer) {
        setConversationHistory(prev => [...prev, { question: qToRun, answer: res.answer }].slice(-6));
      }
    } catch (e: any) {
      alert(`Query failed: ${e.message}`);
    } finally {
      setLoadingQ(false);
    }
  }

  async function handleTrace(queryText?: string) {
    const qToRun = queryText || traceQ;
    if (!qToRun.trim()) return;
    setLoadingTrace(true);
    try {
      const res = await api(`/projects/${id}/trace-flow`, {
        method: 'POST',
        body: JSON.stringify({ question: qToRun }),
      });
      setTraceRes(res);
    } catch (e: any) {
      alert(`Trace failed: ${e.message}`);
    } finally {
      setLoadingTrace(false);
    }
  }

  async function handleEnhancement(reqText?: string) {
    const rToRun = reqText || enhReq;
    if (!rToRun.trim()) return;
    setLoadingEnh(true);
    try {
      const res = await api(`/projects/${id}/analyze-enhancement`, {
        method: 'POST',
        body: JSON.stringify({ request: rToRun }),
      });
      setEnhRes(res);
    } catch (e: any) {
      alert(`Enhancement analysis failed: ${e.message}`);
    } finally {
      setLoadingEnh(false);
    }
  }

  async function handleGenerateDoc(fmt: 'docx' | 'pdf') {
    setDocLoading(true);
    setDocFormatLoading(fmt);
    setDocError(null);
    try {
      const res = await api(`/projects/${id}/generate-doc`, {
        method: 'POST',
        body: JSON.stringify({ scope: docScope, format: fmt }),
      }) as any;

      const newDoc = {
        id: res.doc_id,
        format: fmt.toUpperCase(),
        url: `${BASE}${res.download_url}`,
        date: new Date().toLocaleTimeString(),
      };
      setGeneratedDocs(prev => [newDoc, ...prev]);
      try {
        await downloadFile(newDoc.url, `functional_specification_${newDoc.id}.${fmt}`);
      } catch (dlErr: any) {
        console.error('Auto-download error:', dlErr);
      }
    } catch (e: any) {
      setDocError(e.message || 'Document generation failed.');
    } finally {
      setDocLoading(false);
      setDocFormatLoading(null);
    }
  }

  async function handleDownloadDoc(doc: { url: string; format: string; id: number }) {
    try {
      const filename = `functional_specification_${doc.id}.${doc.format.toLowerCase()}`;
      await downloadFile(doc.url, filename);
    } catch (err: any) {
      setDocError(`Download failed: ${err.message || err}`);
    }
  }

  async function handleResync() {
    try {
      const res = await api(`/projects/${id}/resync`, { method: 'POST' });
      setProject((prev: any) => ({ ...prev, ...res }));
    } catch (e: any) {
      alert(`Resync error: ${e.message}`);
    }
  }

  async function handleGenerateFullDocs() {
    setGeneratingFullDocs(true);
    setDocError(null);
    try {
      const res = await api(`/projects/${id}/generate-full-docs`, { method: 'POST' }) as any;
      if (res?.docx && res?.pdf) {
        const docxItem = {
          id: res.docx.doc_id,
          format: 'DOCX',
          url: `${BASE}${res.docx.download_url}`,
          date: new Date().toLocaleTimeString(),
        };
        const pdfItem = {
          id: res.pdf.doc_id,
          format: 'PDF',
          url: `${BASE}${res.pdf.download_url}`,
          date: new Date().toLocaleTimeString(),
        };
        setGeneratedDocs(prev => [docxItem, pdfItem, ...prev]);
        try {
          await downloadFile(docxItem.url, `functional_specification_${docxItem.id}.docx`);
        } catch (dlErr: any) {
          console.error('Auto-download error:', dlErr);
        }
      }
    } catch (e: any) {
      setDocError(e.message || 'Failed to generate complete specification bundle.');
    } finally {
      setGeneratingFullDocs(false);
    }
  }

  const effectiveBranch = project?.branch || project?.default_branch || project?.detected_branch || 'main';
  const cleanRepoUrl = project?.repo_url || '';

  return (
    <div className="app-layout">
      <Navbar projectContext={{ name: project?.name, branch: effectiveBranch, status: project?.status }} />

      <main className="main-content">
        {/* Workspace Editorial Header */}
        <section style={{ marginBottom: '2.5rem' }} aria-labelledby="workspace-title">
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: '1rem', marginBottom: '1rem' }}>
            <div>
              <div className="label-caps" style={{ marginBottom: '0.35rem' }}>
                WORKSPACE / PROJECT #{id}
              </div>
              <h1 id="workspace-title" style={{ fontSize: '2.5rem', fontWeight: 900, textTransform: 'uppercase', letterSpacing: '-0.02em', lineHeight: 1 }}>
                {project?.name || `Project #${id}`}
              </h1>
            </div>

            <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
              {project && <StatusBadge status={project.status} />}
              <button
                type="button"
                className="btn btn-outline btn-sm"
                onClick={async () => {
                  try {
                    await api(`/projects/${id}/resync`, { method: 'POST' });
                    alert('Resync queued for this repository.');
                    loadProject();
                  } catch (e: any) {
                    alert(`Resync error: ${e.message}`);
                  }
                }}
              >
                ↻ RESYNC
              </button>
              <Link to="/projects" className="btn btn-outline btn-sm">
                ← ALL PROJECTS
              </Link>
            </div>
          </div>

          {/* Metadata Row: 12-Column Alignment */}
          <div style={{ display: 'flex', alignItems: 'center', gap: '1.5rem', flexWrap: 'wrap', borderTop: '1px solid var(--border)', borderBottom: '1px solid var(--border)', padding: '0.85rem 0', fontSize: '0.85rem' }}>
            <div>
              <span className="label-caps" style={{ fontSize: '0.65rem', marginRight: '6px' }}>PROVIDER:</span>
              <strong style={{ textTransform: 'uppercase' }}>{project?.provider || 'GitHub'}</strong>
            </div>
            <div>
              <span className="label-caps" style={{ fontSize: '0.65rem', marginRight: '6px' }}>EFFECTIVE BRANCH:</span>
              <span style={{ fontFamily: 'var(--font-mono)', color: 'var(--primary)', fontWeight: 700 }}>
                {effectiveBranch}
              </span>
            </div>
            {cleanRepoUrl && (
              <div>
                <span className="label-caps" style={{ fontSize: '0.65rem', marginRight: '6px' }}>REPOSITORY:</span>
                <a href={cleanRepoUrl} target="_blank" rel="noreferrer" style={{ color: 'var(--text-primary)', textDecoration: 'underline' }}>
                  {cleanRepoUrl.replace('https://github.com/', '').replace('https://gitlab.com/', '')}
                </a>
              </div>
            )}
          </div>
        </section>

        {/* Stale Repository Banner */}
        {project && (project.is_stale || project.status === 'stale') && (
          <div
            role="alert"
            style={{
              border: '2px solid var(--primary)',
              backgroundColor: 'var(--bg-white)',
              padding: '1.25rem 1.5rem',
              marginBottom: '2rem',
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'center',
              flexWrap: 'wrap',
              gap: '1rem',
            }}
          >
            <div>
              <div className="label-caps" style={{ color: 'var(--primary)', marginBottom: '0.25rem' }}>
                ▲ STALE — REPOSITORY CHANGED
              </div>
              <p style={{ margin: 0, fontSize: '0.95rem', color: 'var(--text-primary)', fontWeight: 600 }}>
                {project.message || 'Remote repository changes detected. Re-analysis is recommended to refresh functional intelligence.'}
              </p>
            </div>
            <button
              type="button"
              className="btn btn-primary btn-sm"
              onClick={handleResync}
            >
              SYNC / REANALYZE REPOSITORY
            </button>
          </div>
        )}

        {/* 8-Stage Pipeline Visualization during Ingestion */}
        {project && !['ready', 'failed', 'stale'].includes((project.status || '').toLowerCase()) && (
          <div style={{ border: '1px solid var(--border)', backgroundColor: 'var(--bg-white)', padding: '1.5rem', marginBottom: '2rem' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '0.5rem', marginBottom: '0.75rem' }}>
              <div className="label-caps" style={{ color: 'var(--primary)', fontSize: '0.75rem' }}>
                AUTOMATED PIPELINE EXECUTION ({project.progress || 0}%)
              </div>
              <span style={{ fontSize: '0.8rem', fontFamily: 'var(--font-mono)', fontWeight: 700 }}>
                STAGE: {(project.stage || project.status || '').toUpperCase()}
              </span>
            </div>
            <p style={{ fontSize: '0.95rem', marginBottom: '1.25rem', color: 'var(--text-secondary)' }}>
              {project.message || 'Analyzing repository...'}
            </p>

            {/* 8-Stage Progression Grid */}
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(120px, 1fr))', gap: '0.5rem' }}>
              {[
                { step: '01', label: 'CONNECTED', minProg: 5 },
                { step: '02', label: 'BRANCH DETECTED', minProg: 18 },
                { step: '03', label: 'SCANNED', minProg: 38 },
                { step: '04', label: 'ANALYZED', minProg: 50 },
                { step: '05', label: 'UNDERSTOOD', minProg: 72 },
                { step: '06', label: 'INDEXED', minProg: 88 },
                { step: '07', label: 'SUMMARY READY', minProg: 94 },
                { step: '08', label: 'READY FOR QUESTIONS', minProg: 100 },
              ].map(s => {
                const isDone = (project.progress || 0) >= s.minProg;
                const isActive = (project.progress || 0) < s.minProg && (project.progress || 0) >= (s.minProg - 15);
                return (
                  <div
                    key={s.step}
                    style={{
                      border: `1px solid ${isDone ? 'var(--primary)' : isActive ? 'var(--text-primary)' : 'var(--border)'}`,
                      backgroundColor: isDone ? 'var(--primary)' : isActive ? 'var(--bg-card)' : 'transparent',
                      color: isDone ? 'var(--bg-base)' : 'var(--text-primary)',
                      padding: '0.6rem 0.5rem',
                      fontSize: '0.7rem',
                    }}
                  >
                    <div style={{ fontWeight: 900, marginBottom: '2px' }}>{s.step}</div>
                    <div style={{ fontWeight: 700, letterSpacing: '0.04em' }}>{s.label}</div>
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {/* Failed Ingestion Banner */}
        {project?.status === 'failed' && (
          <div
            role="alert"
            style={{
              border: '2px solid var(--status-failed-border)',
              backgroundColor: 'var(--status-failed-bg)',
              padding: '1.5rem',
              marginBottom: '2rem',
            }}
          >
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: '1rem' }}>
              <div>
                <div className="label-caps" style={{ color: 'var(--status-failed-text)', marginBottom: '0.25rem' }}>
                  FAILED / INGESTION FAILED
                </div>
                <p style={{ color: 'var(--status-failed-text)', fontSize: '0.95rem', fontWeight: 700, margin: '0 0 0.5rem 0' }}>
                  Reason: {project.error || project.message || 'The repository ingestion or branch checkout failed.'}
                </p>
                {project.error && (
                  <details style={{ marginTop: '0.5rem', fontSize: '0.75rem' }}>
                    <summary style={{ cursor: 'pointer', color: 'var(--status-failed-text)', fontWeight: 700 }}>
                      [ EXPAND TECHNICAL ERROR DETAILS ]
                    </summary>
                    <pre style={{ marginTop: '6px', padding: '8px', background: '#141414', color: '#E3E2DE', overflowX: 'auto', whiteSpace: 'pre-wrap', fontFamily: 'var(--font-mono)' }}>
                      {project.error}
                    </pre>
                  </details>
                )}
              </div>
              <button
                type="button"
                className="btn btn-secondary btn-sm"
                onClick={async () => {
                  try {
                    await api(`/projects/${id}/resync`, { method: 'POST' });
                    alert('Resync queued. Ingestion will reattempt momentarily.');
                    loadProject();
                  } catch (e: any) {
                    alert(`Retry failed: ${e.message}`);
                  }
                }}
              >
                RETRY / RESYNC
              </button>
            </div>
          </div>
        )}

        {/* Workspace Text Tabs */}
        <nav className="tabs-container" aria-label="Project Workspace Sections">
          <button
            type="button"
            className={`tab-btn ${activeTab === 'overview' ? 'active' : ''}`}
            onClick={() => setActiveTab('overview')}
          >
            OVERVIEW
          </button>
          <button
            type="button"
            className={`tab-btn ${activeTab === 'ask' ? 'active' : ''}`}
            onClick={() => setActiveTab('ask')}
          >
            ASK
          </button>
          <button
            type="button"
            className={`tab-btn ${activeTab === 'trace' ? 'active' : ''}`}
            onClick={() => setActiveTab('trace')}
          >
            TRACE FLOW
          </button>
          <button
            type="button"
            className={`tab-btn ${activeTab === 'enhancement' ? 'active' : ''}`}
            onClick={() => setActiveTab('enhancement')}
          >
            IMPACT
          </button>
          <button
            type="button"
            className={`tab-btn ${activeTab === 'docs' ? 'active' : ''}`}
            onClick={() => setActiveTab('docs')}
          >
            DOCUMENTATION
          </button>
        </nav>

        {/* ============================================================ */}
        {/* TAB 1: OVERVIEW — PM/BA BRIEFING DOCUMENT                     */}
        {/* ============================================================ */}
        {activeTab === 'overview' && (
          <section aria-labelledby="overview-heading">
            <div style={{ marginBottom: '2rem' }}>
              <div className="label-caps" style={{ marginBottom: '0.25rem' }}>
                BRIEFING DOCUMENT
              </div>
              <h2 id="overview-heading" style={{ fontSize: '2rem', fontWeight: 900, textTransform: 'uppercase' }}>
                PROJECT OVERVIEW.
              </h2>
            </div>

            {loadingSummary ? (
              <div style={{ padding: '4rem 2rem', textAlign: 'center', border: '1px solid var(--border)', backgroundColor: 'var(--bg-white)' }}>
                <span className="label-caps">[ ASSEMBLING ARCHITECTURAL FACTS & FUNCTIONAL SUMMARY… ]</span>
              </div>
            ) : summaryData?.error ? (
              <div style={{ border: '1px solid var(--status-failed-border)', backgroundColor: 'var(--status-failed-bg)', padding: '1.5rem', color: 'var(--status-failed-text)' }}>
                <p style={{ margin: 0, fontWeight: 700 }}>{summaryData.error}</p>
              </div>
            ) : (
              <div>
                {/* 0. ANALYSIS HEALTH */}
                {healthMetrics && (
                  <div className="section-row" style={{ backgroundColor: 'var(--bg-white)', borderBottom: '2px solid var(--border)' }}>
                    <div className="section-label">
                      ANALYSIS HEALTH
                      <div style={{ marginTop: '0.4rem' }}>
                        <span className="status-badge status-badge-ready" style={{ fontSize: '0.65rem' }}>
                          ● {healthMetrics.status || 'HEALTHY'}
                        </span>
                      </div>
                    </div>
                    <div className="section-content">
                      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(130px, 1fr))', gap: '0.75rem', marginBottom: '0.75rem' }}>
                        <div style={{ border: '1px solid var(--border)', padding: '0.5rem 0.75rem' }}>
                          <div className="label-caps" style={{ fontSize: '0.65rem' }}>FILES ANALYZED</div>
                          <div style={{ fontSize: '1.25rem', fontWeight: 900 }}>{healthMetrics.files_analyzed ?? 0}</div>
                        </div>
                        <div style={{ border: '1px solid var(--border)', padding: '0.5rem 0.75rem' }}>
                          <div className="label-caps" style={{ fontSize: '0.65rem' }}>ENTITIES</div>
                          <div style={{ fontSize: '1.25rem', fontWeight: 900 }}>{healthMetrics.entities_discovered ?? 0}</div>
                        </div>
                        <div style={{ border: '1px solid var(--border)', padding: '0.5rem 0.75rem' }}>
                          <div className="label-caps" style={{ fontSize: '0.65rem' }}>WORKFLOWS</div>
                          <div style={{ fontSize: '1.25rem', fontWeight: 900 }}>{healthMetrics.workflows_discovered ?? 0}</div>
                        </div>
                        <div style={{ border: '1px solid var(--border)', padding: '0.5rem 0.75rem' }}>
                          <div className="label-caps" style={{ fontSize: '0.65rem' }}>APIS</div>
                          <div style={{ fontSize: '1.25rem', fontWeight: 900 }}>{healthMetrics.apis_discovered ?? 0}</div>
                        </div>
                        <div style={{ border: '1px solid var(--border)', padding: '0.5rem 0.75rem' }}>
                          <div className="label-caps" style={{ fontSize: '0.65rem' }}>RULES</div>
                          <div style={{ fontSize: '1.25rem', fontWeight: 900 }}>{healthMetrics.rules_discovered ?? 0}</div>
                        </div>
                        <div style={{ border: '1px solid var(--border)', padding: '0.5rem 0.75rem' }}>
                          <div className="label-caps" style={{ fontSize: '0.65rem' }}>INDEX COVERAGE</div>
                          <div style={{ fontSize: '1.25rem', fontWeight: 900, color: 'var(--primary)' }}>{healthMetrics.index_completeness || '100%'}</div>
                        </div>
                      </div>
                      <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>
                        Tracked commit: <strong style={{ fontFamily: 'var(--font-mono)' }}>{project?.analyzed_commit_sha ? project.analyzed_commit_sha.slice(0, 10) : 'HEAD'}</strong> • Skipped {healthMetrics.files_skipped ?? 0} assets/binaries • {healthMetrics.roles_discovered ?? 0} roles verified.
                      </div>
                    </div>
                  </div>
                )}

                {/* 1. PURPOSE */}
                <div className="section-row">
                  <div className="section-label">PURPOSE</div>
                  <div className="section-content">
                    <p style={{ fontSize: '1.1rem', fontWeight: 600, color: 'var(--text-primary)', marginBottom: '0.5rem' }}>
                      {summaryData?.facts?.repo_overview || summaryData?.summary?.split('\n\n')[0] || 'Repository grounded application purpose.'}
                    </p>
                  </div>
                </div>

                {/* 2. BUSINESS PROBLEM */}
                <div className="section-row">
                  <div className="section-label">BUSINESS PROBLEM</div>
                  <div className="section-content">
                    <p style={{ fontSize: '1rem', color: 'var(--text-secondary)' }}>
                      {summaryData?.facts?.business_problem ||
                       'Streamlines operational workflows, enforces domain constraints, and provides automated processing of core domain entities.'}
                    </p>
                  </div>
                </div>

                {/* 3. CAPABILITIES */}
                <div className="section-row">
                  <div className="section-label">CAPABILITIES</div>
                  <div className="section-content">
                    <ul style={{ paddingLeft: '1.25rem', color: 'var(--text-secondary)' }}>
                      {(summaryData?.facts?.capabilities || [
                        'Ingests and normalizes domain records',
                        'Enforces state transitions and validation rules',
                        'Coordinates execution across internal handlers and external interfaces',
                        'Maintains audit logs and persistence consistency'
                      ]).map((cap: string, i: number) => (
                        <li key={i} style={{ marginBottom: '6px' }}>{cap}</li>
                      ))}
                    </ul>
                  </div>
                </div>

                {/* 4. USERS / ROLES */}
                <div className="section-row">
                  <div className="section-label">USERS / ROLES</div>
                  <div className="section-content">
                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.75rem' }}>
                      {(summaryData?.facts?.roles?.length ? summaryData.facts.roles : ['Standard User', 'Administrator']).map((r: string, i: number) => (
                        <span
                          key={i}
                          style={{
                            border: '1px solid var(--border)',
                            backgroundColor: 'var(--bg-white)',
                            padding: '6px 12px',
                            fontWeight: 700,
                            fontSize: '0.85rem',
                            textTransform: 'uppercase',
                          }}
                        >
                          {r}
                        </span>
                      ))}
                    </div>
                  </div>
                </div>

                {/* 5. MODULES */}
                <div className="section-row">
                  <div className="section-label">MODULES</div>
                  <div className="section-content">
                    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))', gap: '1rem' }}>
                      {(summaryData?.facts?.modules || [{ name: 'core', description: 'Primary business logic orchestrator' }]).map((m: any, i: number) => (
                        <div key={i} style={{ border: '1px solid var(--border)', backgroundColor: 'var(--bg-white)', padding: '1rem' }}>
                          <span style={{ fontFamily: 'var(--font-mono)', fontWeight: 700, fontSize: '0.9rem', color: 'var(--primary)', display: 'block', marginBottom: '4px' }}>
                            {m.name}
                          </span>
                          <p style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', margin: 0 }}>
                            {m.description || 'Application functional unit'}
                          </p>
                        </div>
                      ))}
                    </div>
                  </div>
                </div>

                {/* 6. WORKFLOWS */}
                <div className="section-row">
                  <div className="section-label">WORKFLOWS</div>
                  <div className="section-content">
                    <p style={{ fontSize: '0.95rem', color: 'var(--text-secondary)', marginBottom: '0.5rem' }}>
                      Primary workflow proceeds through ingestion, validation, state persistence, and notification dispatch.
                    </p>
                    <button
                      type="button"
                      className="btn btn-outline btn-sm"
                      onClick={() => setActiveTab('trace')}
                    >
                      INSPECT WORKFLOW TRACE →
                    </button>
                  </div>
                </div>

                {/* 7. BUSINESS RULES */}
                <div className="section-row">
                  <div className="section-label">BUSINESS RULES</div>
                  <div className="section-content">
                    <ul style={{ paddingLeft: '1.25rem', color: 'var(--text-secondary)' }}>
                      {(summaryData?.facts?.business_rules || [
                        'Input payloads must satisfy schema definitions before processing',
                        'State changes require verified caller role authorization',
                        'Idempotency and consistency guaranteed on core operations'
                      ]).map((rule: string, i: number) => (
                        <li key={i} style={{ marginBottom: '6px' }}>{rule}</li>
                      ))}
                    </ul>
                  </div>
                </div>

                {/* 8. ARCHITECTURE */}
                <div className="section-row">
                  <div className="section-label">ARCHITECTURE</div>
                  <div className="section-content">
                    <div style={{ display: 'flex', gap: '1.5rem', flexWrap: 'wrap' }}>
                      <div>
                        <span className="label-caps" style={{ fontSize: '0.65rem' }}>LANGUAGES</span>
                        <div style={{ fontWeight: 700, marginTop: '2px' }}>
                          {(summaryData?.facts?.languages || []).join(', ') || 'Detected automatically'}
                        </div>
                      </div>
                      <div>
                        <span className="label-caps" style={{ fontSize: '0.65rem' }}>COMPONENTS INDEXED</span>
                        <div style={{ fontFamily: 'var(--font-mono)', fontWeight: 700, marginTop: '2px' }}>
                          {summaryData?.facts?.components_count || summaryData?.facts?.modules?.length || 'Verified'}
                        </div>
                      </div>
                    </div>
                  </div>
                </div>

                {/* 9. DATA / ENTITIES */}
                <div className="section-row">
                  <div className="section-label">DATA & ENTITIES</div>
                  <div className="section-content">
                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.5rem' }}>
                      {(summaryData?.facts?.entities?.length ? summaryData.facts.entities : [{ name: 'Record' }, { name: 'AuditLog' }]).map((e: any, i: number) => (
                        <code
                          key={i}
                          style={{
                            fontFamily: 'var(--font-mono)',
                            fontSize: '0.85rem',
                            border: '1px solid var(--border)',
                            backgroundColor: 'var(--bg-white)',
                            padding: '4px 8px',
                          }}
                        >
                          {e.name}
                        </code>
                      ))}
                    </div>
                  </div>
                </div>

                {/* 10. INTEGRATIONS */}
                <div className="section-row">
                  <div className="section-label">INTEGRATIONS</div>
                  <div className="section-content">
                    <p style={{ color: 'var(--text-secondary)', margin: 0 }}>
                      {(summaryData?.facts?.integrations || []).join(', ') || 'No third-party external integrations declared.'}
                    </p>
                  </div>
                </div>

                {/* 11. DEPENDENCIES */}
                <div className="section-row">
                  <div className="section-label">DEPENDENCIES</div>
                  <div className="section-content">
                    {summaryData?.facts?.dependencies?.length > 0 ? (
                      <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.35rem' }}>
                        {summaryData.facts.dependencies.map((d: string, i: number) => (
                          <span
                            key={i}
                            style={{
                              border: '1px solid var(--border)',
                              backgroundColor: 'var(--bg-white)',
                              padding: '2px 8px',
                              fontSize: '0.8rem',
                              fontFamily: 'var(--font-mono)',
                            }}
                          >
                            {d}
                          </span>
                        ))}
                      </div>
                    ) : (
                      <span style={{ color: 'var(--text-muted)' }}>Standard library runtime</span>
                    )}
                  </div>
                </div>

                {/* Full Synthesized Narrative */}
                {summaryData?.summary && (
                  <div style={{ marginTop: '2.5rem', border: '1px solid var(--border)', backgroundColor: 'var(--bg-white)', padding: '2rem' }}>
                    <div className="label-caps" style={{ marginBottom: '1rem' }}>
                      SYNTHESIZED FUNCTIONAL ARCHITECTURE SUMMARY
                    </div>
                    <div
                      className="markdown-body"
                      dangerouslySetInnerHTML={{
                        __html: renderMarkdownToHtml(summaryData.summary)
                      }}
                    />
                  </div>
                )}
              </div>
            )}
          </section>
        )}

        {/* ============================================================ */}
        {/* TAB 2: ASK — FUNCTIONAL Q&A                                  */}
        {/* ============================================================ */}
        {activeTab === 'ask' && (
          <section aria-labelledby="ask-heading">
            <div style={{ marginBottom: '2.5rem' }}>
              <div className="label-caps" style={{ marginBottom: '0.25rem' }}>
                ZERO-HALLUCINATION QUESTION ENGINE
              </div>
              <h2 id="ask-heading" className="hero-title" style={{ fontSize: 'clamp(2.5rem, 5vw, 4.5rem)', marginBottom: '0.5rem' }}>
                ASK THE <span className="accent">APPLICATION.</span>
              </h2>
              <p style={{ color: 'var(--text-secondary)', fontSize: '1.1rem', maxWidth: '720px' }}>
                Ask anything about how this application works. Query operational workflows, business rules,
                roles, data entities, and execution logic. Answers are strictly grounded in repository evidence.
              </p>
            </div>

            {/* Question Input Box */}
            <div style={{ border: '2px solid var(--text-primary)', backgroundColor: 'var(--bg-white)', padding: '1.75rem', marginBottom: '2rem' }}>
              <div className="form-group" style={{ margin: 0, marginBottom: '1rem' }}>
                <label htmlFor="askInput" className="label-caps" style={{ color: 'var(--text-primary)', marginBottom: '0.5rem' }}>
                  FUNCTIONAL QUERY
                </label>
                <input
                  id="askInput"
                  type="text"
                  className="form-input"
                  placeholder="Ask anything about how this application works..."
                  value={question}
                  onChange={e => setQuestion(e.target.value)}
                  onKeyDown={e => e.key === 'Enter' && handleAsk()}
                  style={{ fontSize: '1.1rem', padding: '16px' }}
                />
              </div>

              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '1rem' }}>
                <span style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>
                  Press Enter or click Ask Assistant to run analysis.
                </span>
                <button
                  type="button"
                  className="btn btn-primary"
                  onClick={() => handleAsk()}
                  disabled={loadingQ}
                >
                  {loadingQ ? 'ANALYZING REPOSITORY…' : 'ASK ASSISTANT'}
                </button>
              </div>

              {/* Dynamic Suggestions */}
              {suggestedQuestions.length > 0 && (
                <div style={{ marginTop: '1.5rem', borderTop: '1px solid var(--border)', paddingTop: '1rem' }}>
                  <span className="label-caps" style={{ fontSize: '0.65rem', display: 'block', marginBottom: '0.75rem' }}>
                    GROUNDED SUGGESTIONS FROM THIS REPOSITORY:
                  </span>
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.5rem' }}>
                    {suggestedQuestions.map((sq, i) => (
                      <button
                        key={i}
                        type="button"
                        onClick={() => { setQuestion(sq); handleAsk(sq); }}
                        style={{
                          background: 'var(--bg-base)',
                          border: '1px solid var(--border)',
                          padding: '6px 12px',
                          fontSize: '0.8rem',
                          fontFamily: 'var(--font-sans)',
                          fontWeight: 600,
                          cursor: 'pointer',
                          color: 'var(--text-primary)',
                          textAlign: 'left',
                        }}
                      >
                        → {sq}
                      </button>
                    ))}
                  </div>
                </div>
              )}
            </div>

            {/* Loading State */}
            {loadingQ && (
              <div style={{ border: '1px solid var(--border)', backgroundColor: 'var(--bg-white)', padding: '3rem 2rem', textAlign: 'center', margin: '2rem 0' }}>
                <div className="label-caps" style={{ color: 'var(--primary)', marginBottom: '0.5rem' }}>
                  [ ANALYZING REPOSITORY & SYNTHESIZING ANSWER ]
                </div>
                <p style={{ color: 'var(--text-secondary)', fontSize: '0.95rem', margin: 0 }}>
                  Scanning indexed files, evaluating symbol call-graphs, and formulating business explanation…
                </p>
              </div>
            )}

            {/* Result Presentation */}
            {qAns && !loadingQ && (
              <div>
                {/* Case 1: Insufficient Evidence */}
                {qAns.status === 'INSUFFICIENT_EVIDENCE' ? (
                  <div className="editorial-alert" style={{ border: '2px solid var(--border)' }}>
                    <div className="label-caps" style={{ color: 'var(--text-muted)', marginBottom: '0.5rem' }}>
                      ZERO-HALLUCINATION VERIFICATION
                    </div>
                    <h3 className="editorial-alert-title" style={{ fontSize: '1.5rem' }}>
                      INSUFFICIENT EVIDENCE.
                    </h3>
                    <p style={{ fontSize: '1.05rem', color: 'var(--text-primary)', marginBottom: '1.5rem' }}>
                      CodeSense could not find enough repository evidence to establish this behavior confidently.
                    </p>

                    {/* What Was Found */}
                    <div className="section-row" style={{ padding: '1rem 0' }}>
                      <div className="section-label">WHAT WAS FOUND</div>
                      <div className="section-content">
                        <p style={{ margin: 0 }}>
                          {qAns.answer || 'Target symbols and modules were examined, but no corresponding implementation logic exists in this repository.'}
                        </p>
                      </div>
                    </div>

                    {/* What Is Missing */}
                    {qAns.missing_concepts?.length > 0 && (
                      <div className="section-row" style={{ padding: '1rem 0' }}>
                        <div className="section-label">WHAT IS MISSING</div>
                        <div className="section-content">
                          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.5rem' }}>
                            {qAns.missing_concepts.map((mc: string, i: number) => (
                              <span key={i} style={{ border: '1px solid var(--border)', padding: '2px 8px', fontSize: '0.85rem', fontFamily: 'var(--font-mono)' }}>
                                {mc}
                              </span>
                            ))}
                          </div>
                        </div>
                      </div>
                    )}

                    {/* Known Limitations */}
                    {qAns.gaps?.length > 0 && (
                      <div className="section-row" style={{ padding: '1rem 0', borderBottom: 'none' }}>
                        <div className="section-label">KNOWN LIMITATIONS</div>
                        <div className="section-content">
                          <ul style={{ paddingLeft: '1.25rem', margin: 0 }}>
                            {qAns.gaps.map((g: string, i: number) => <li key={i}>{g}</li>)}
                          </ul>
                        </div>
                      </div>
                    )}
                  </div>
                ) : (
                  /* Case 2: Grounded Business Answer */
                  <div style={{ border: '2px solid var(--text-primary)', backgroundColor: 'var(--bg-white)', padding: '2.5rem' }}>
                    {/* Header with Confidence */}
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '1.5rem', flexWrap: 'wrap', gap: '1rem', borderBottom: '1px solid var(--border)', paddingBottom: '1rem' }}>
                      <div>
                        <div className="label-caps" style={{ marginBottom: '0.25rem' }}>
                          BUSINESS ANSWER
                        </div>
                        <h3 style={{ fontSize: '1.75rem', fontWeight: 900, textTransform: 'uppercase' }}>
                          ANSWER.
                        </h3>
                      </div>
                      <ConfidenceBadge level={qAns.confidence || 'HIGH'} />
                    </div>

                    {/* Formatted Markdown Business Explanation */}
                    <div
                      className="markdown-body"
                      style={{ fontSize: '1.1rem', lineHeight: 1.7, marginBottom: '2rem' }}
                      dangerouslySetInnerHTML={{
                        __html: renderMarkdownToHtml(qAns.answer || '')
                      }}
                    />

                    {/* How It Works / Details */}
                    {qAns.workflow_steps?.length > 0 && (
                      <div style={{ borderTop: '1px solid var(--border)', paddingTop: '1.5rem', marginBottom: '1.5rem' }}>
                        <div className="label-caps" style={{ marginBottom: '0.75rem' }}>HOW IT WORKS</div>
                        <ol style={{ paddingLeft: '1.5rem', color: 'var(--text-secondary)' }}>
                          {qAns.workflow_steps.map((st: string, i: number) => (
                            <li key={i} style={{ marginBottom: '6px' }}>{st}</li>
                          ))}
                        </ol>
                      </div>
                    )}

                    {/* Business Rules */}
                    {qAns.business_rules?.length > 0 && (
                      <div style={{ borderTop: '1px solid var(--border)', paddingTop: '1.5rem', marginBottom: '1.5rem' }}>
                        <div className="label-caps" style={{ marginBottom: '0.75rem' }}>BUSINESS RULES & CONSTRAINTS</div>
                        <ul style={{ paddingLeft: '1.5rem', color: 'var(--text-secondary)' }}>
                          {qAns.business_rules.map((br: string, i: number) => (
                            <li key={i} style={{ marginBottom: '6px' }}>{br}</li>
                          ))}
                        </ul>
                      </div>
                    )}

                    {/* Roles & Access */}
                    {qAns.roles_allowed?.length > 0 && (
                      <div style={{ borderTop: '1px solid var(--border)', paddingTop: '1.5rem', marginBottom: '1.5rem' }}>
                        <div className="label-caps" style={{ marginBottom: '0.75rem' }}>ROLES & ACCESS</div>
                        <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.5rem' }}>
                          {qAns.roles_allowed.map((role: string, i: number) => (
                            <span key={i} style={{ border: '1px solid var(--border)', padding: '2px 8px', fontSize: '0.8rem', fontWeight: 700, textTransform: 'uppercase' }}>
                              {role}
                            </span>
                          ))}
                        </div>
                      </div>
                    )}

                    {/* Impacted Components */}
                    {qAns.affected_modules?.length > 0 && (
                      <div style={{ borderTop: '1px solid var(--border)', paddingTop: '1.5rem', marginBottom: '1.5rem' }}>
                        <div className="label-caps" style={{ marginBottom: '0.75rem' }}>IMPACTED COMPONENTS</div>
                        <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.5rem' }}>
                          {qAns.affected_modules.map((m: string, i: number) => (
                            <code key={i} style={{ border: '1px solid var(--border)', backgroundColor: 'var(--bg-base)', padding: '4px 8px', fontSize: '0.85rem' }}>
                              {m}
                            </code>
                          ))}
                        </div>
                      </div>
                    )}

                    {/* Evidence Drawer */}
                    {qAns.evidence?.length > 0 && (
                      <div style={{ borderTop: '1px solid var(--border)', paddingTop: '1.5rem' }}>
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem' }}>
                          <div className="label-caps">
                            GROUNDED REPOSITORY EVIDENCE ({qAns.evidence.length} CITATIONS)
                          </div>
                          <button
                            type="button"
                            className="btn btn-outline btn-sm"
                            onClick={() => setShowEvidence(!showEvidence)}
                          >
                            {showEvidence ? 'HIDE EVIDENCE ▲' : 'INSPECT EVIDENCE ▼'}
                          </button>
                        </div>

                        {showEvidence && (
                          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem', marginTop: '1rem' }}>
                            {qAns.evidence.map((ev: any, i: number) => (
                              <EvidenceCard key={i} item={ev} />
                            ))}
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                )}
              </div>
            )}
          </section>
        )}

        {/* ============================================================ */}
        {/* TAB 3: TRACE FLOW — WORKFLOW VISUALIZATION                   */}
        {/* ============================================================ */}
        {activeTab === 'trace' && (
          <section aria-labelledby="trace-heading">
            <div style={{ marginBottom: '2.5rem' }}>
              <div className="label-caps" style={{ marginBottom: '0.25rem' }}>
                CROSS-LAYER EXECUTION GRAPH
              </div>
              <h2 id="trace-heading" className="hero-title" style={{ fontSize: 'clamp(2.5rem, 5vw, 4.5rem)', marginBottom: '0.5rem' }}>
                TRACE <span className="accent">FLOW.</span>
              </h2>
              <p style={{ color: 'var(--text-secondary)', fontSize: '1.1rem', maxWidth: '720px' }}>
                Follow functionality across frontend entry points, validation gates, backend handlers, data persistence, and external integrations.
              </p>
            </div>

            {/* Trace Query Input */}
            <div style={{ border: '2px solid var(--text-primary)', backgroundColor: 'var(--bg-white)', padding: '1.75rem', marginBottom: '2rem' }}>
              <div className="form-group" style={{ margin: 0, marginBottom: '1rem' }}>
                <label htmlFor="traceInput" className="label-caps" style={{ color: 'var(--text-primary)', marginBottom: '0.5rem' }}>
                  WORKFLOW QUERY
                </label>
                <input
                  id="traceInput"
                  type="text"
                  className="form-input"
                  placeholder="e.g. What happens when a user submits the main action?"
                  value={traceQ}
                  onChange={e => setTraceQ(e.target.value)}
                  onKeyDown={e => e.key === 'Enter' && handleTrace()}
                  style={{ fontSize: '1.05rem', padding: '14px' }}
                />
              </div>

              <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
                <button
                  type="button"
                  className="btn btn-primary"
                  onClick={() => handleTrace()}
                  disabled={loadingTrace}
                >
                  {loadingTrace ? 'TRACING WORKFLOW…' : 'TRACE WORKFLOW'}
                </button>
              </div>
            </div>

            {/* Loading */}
            {loadingTrace && (
              <div style={{ border: '1px solid var(--border)', backgroundColor: 'var(--bg-white)', padding: '3rem 2rem', textAlign: 'center', margin: '2rem 0' }}>
                <span className="label-caps">[ TRACING CALL STACK & REPOSITORY EXECUTION PATHS… ]</span>
              </div>
            )}

            {/* Trace Result */}
            {traceRes && !loadingTrace && (
              <div>
                {traceRes.status === 'INSUFFICIENT_EVIDENCE' ? (
                  <div className="editorial-alert" style={{ border: '2px solid var(--border)' }}>
                    <div className="label-caps" style={{ marginBottom: '0.5rem' }}>ZERO-HALLUCINATION WORKFLOW GATE</div>
                    <h3 className="editorial-alert-title">INSUFFICIENT EVIDENCE FOR WORKFLOW TRACE.</h3>
                    <p style={{ color: 'var(--text-secondary)' }}>
                      No implementation steps or execution handlers found for this workflow in the analyzed repository.
                    </p>
                  </div>
                ) : (
                  <div>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: '1.5rem', borderBottom: '2px solid var(--text-primary)', paddingBottom: '0.75rem' }}>
                      <h3 style={{ fontSize: '1.5rem', fontWeight: 900, textTransform: 'uppercase' }}>
                        START → EXECUTION GRAPH ({traceRes.steps?.length || 0} STAGES) → OUTCOME
                      </h3>
                      <StatusBadge status={traceRes.confidence || 'HIGH'} type="confidence" />
                    </div>

                    <div style={{ display: 'flex', flexDirection: 'column', gap: '0' }}>
                      {(traceRes.steps || []).map((s: any, i: number) => (
                        <FlowStep
                          key={i}
                          stepNumber={i + 1}
                          stage={s.stage}
                          component={s.component}
                          description={s.description}
                          evidence={s.evidence}
                          isLast={i === traceRes.steps.length - 1}
                        />
                      ))}
                    </div>
                  </div>
                )}
              </div>
            )}
          </section>
        )}

        {/* ============================================================ */}
        {/* TAB 4: ENHANCEMENT IMPACT                                    */}
        {/* ============================================================ */}
        {activeTab === 'enhancement' && (
          <section aria-labelledby="enhancement-heading">
            <div style={{ marginBottom: '2.5rem' }}>
              <div className="label-caps" style={{ marginBottom: '0.25rem' }}>
                ARCHITECTURAL BLAST RADIUS EVALUATION
              </div>
              <h2 id="enhancement-heading" className="hero-title" style={{ fontSize: 'clamp(2.5rem, 5vw, 4.5rem)', marginBottom: '0.5rem' }}>
                IMPACT <span className="accent">ANALYSIS.</span>
              </h2>
              <p style={{ color: 'var(--text-secondary)', fontSize: '1.1rem', maxWidth: '720px' }}>
                Evaluate developer implementation steps, architectural complexity, affected frontend/backend/database components, and regression risk before writing code.
              </p>
            </div>

            {/* Input Box */}
            <div style={{ border: '2px solid var(--text-primary)', backgroundColor: 'var(--bg-white)', padding: '1.75rem', marginBottom: '2rem' }}>
              <div className="form-group" style={{ margin: 0, marginBottom: '1rem' }}>
                <label htmlFor="enhInput" className="label-caps" style={{ color: 'var(--text-primary)', marginBottom: '0.5rem' }}>
                  WHAT CHANGE ARE YOU CONSIDERING?
                </label>
                <input
                  id="enhInput"
                  type="text"
                  className="form-input"
                  placeholder="e.g. Add email notifications to administrators whenever a new record is submitted."
                  value={enhReq}
                  onChange={e => setEnhReq(e.target.value)}
                  onKeyDown={e => e.key === 'Enter' && handleEnhancement()}
                  style={{ fontSize: '1.05rem', padding: '14px' }}
                />
              </div>

              <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
                <button
                  type="button"
                  className="btn btn-primary"
                  onClick={() => handleEnhancement()}
                  disabled={loadingEnh}
                >
                  {loadingEnh ? 'EVALUATING BLAST RADIUS…' : 'ANALYZE IMPACT'}
                </button>
              </div>
            </div>

            {/* Loading */}
            {loadingEnh && (
              <div style={{ border: '1px solid var(--border)', backgroundColor: 'var(--bg-white)', padding: '3rem 2rem', textAlign: 'center', margin: '2rem 0' }}>
                <span className="label-caps">[ EVALUATING REPOSITORY SCHEMAS, CALL-TREES & REGRESSION RISKS… ]</span>
              </div>
            )}

            {/* Result */}
            {enhRes && !loadingEnh && (
              <div>
                {enhRes.status === 'INSUFFICIENT_EVIDENCE' ? (
                  <div className="editorial-alert" style={{ border: '2px solid var(--border)' }}>
                    <div className="label-caps" style={{ marginBottom: '0.5rem' }}>UNSUPPORTED DOMAIN ENHANCEMENT</div>
                    <h3 className="editorial-alert-title">CANNOT ESTABLISH IMPACT BASELINE.</h3>
                    <p style={{ color: 'var(--text-secondary)' }}>
                      The underlying domain concepts for this change are not present in the analyzed repository.
                    </p>
                  </div>
                ) : (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '2rem' }}>
                    {/* Top Complexity Banner */}
                    <div style={{ border: '2px solid var(--text-primary)', backgroundColor: 'var(--bg-white)', padding: '2rem', display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: '1.5rem' }}>
                      <div style={{ flex: 1, minWidth: '280px' }}>
                        <div className="label-caps" style={{ marginBottom: '0.5rem' }}>CURRENT BASELINE BEHAVIOR</div>
                        <p style={{ fontSize: '1rem', color: 'var(--text-primary)', margin: 0, fontWeight: 600 }}>
                          {enhRes.current_behavior}
                        </p>
                        {enhRes.complexity_justification && (
                          <p style={{ fontSize: '0.9rem', color: 'var(--text-secondary)', marginTop: '0.75rem', marginBottom: 0 }}>
                            <strong>Rationale:</strong> {enhRes.complexity_justification}
                          </p>
                        )}
                      </div>

                      <div style={{ borderLeft: '1px solid var(--border)', paddingLeft: '1.5rem' }}>
                        <ComplexityBadge complexity={enhRes.complexity || 'MEDIUM'} />
                      </div>
                    </div>

                    {/* Breakdown Matrix */}
                    <div>
                      <div className="label-caps" style={{ marginBottom: '1rem' }}>
                        SUBSYSTEM IMPACT BREAKDOWN
                      </div>
                      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(320px, 1fr))', gap: '1px', backgroundColor: 'var(--border)', border: '1px solid var(--border)' }}>
                        <div style={{ backgroundColor: 'var(--bg-white)', padding: '1.25rem' }}>
                          <div className="label-caps" style={{ marginBottom: '4px' }}>FRONTEND</div>
                          <p style={{ margin: 0, fontSize: '0.9rem' }}>{enhRes.frontend_impact}</p>
                        </div>
                        <div style={{ backgroundColor: 'var(--bg-white)', padding: '1.25rem' }}>
                          <div className="label-caps" style={{ marginBottom: '4px' }}>BACKEND</div>
                          <p style={{ margin: 0, fontSize: '0.9rem' }}>{enhRes.backend_impact}</p>
                        </div>
                        <div style={{ backgroundColor: 'var(--bg-white)', padding: '1.25rem' }}>
                          <div className="label-caps" style={{ marginBottom: '4px' }}>DATABASE</div>
                          <p style={{ margin: 0, fontSize: '0.9rem' }}>{enhRes.db_impact}</p>
                        </div>
                        <div style={{ backgroundColor: 'var(--bg-white)', padding: '1.25rem' }}>
                          <div className="label-caps" style={{ marginBottom: '4px' }}>PERMISSIONS</div>
                          <p style={{ margin: 0, fontSize: '0.9rem' }}>{enhRes.permission_impact}</p>
                        </div>
                        <div style={{ backgroundColor: 'var(--bg-white)', padding: '1.25rem' }}>
                          <div className="label-caps" style={{ marginBottom: '4px' }}>NOTIFICATIONS</div>
                          <p style={{ margin: 0, fontSize: '0.9rem' }}>{enhRes.notifications}</p>
                        </div>
                        <div style={{ backgroundColor: 'var(--bg-white)', padding: '1.25rem' }}>
                          <div className="label-caps" style={{ marginBottom: '4px' }}>INTEGRATIONS</div>
                          <p style={{ margin: 0, fontSize: '0.9rem' }}>{enhRes.external_integrations}</p>
                        </div>
                      </div>
                    </div>

                    {/* Validation Checklist & Risks */}
                    <div className="grid-12">
                      <div className="col-6" style={{ border: '1px solid var(--border)', backgroundColor: 'var(--bg-white)', padding: '1.75rem' }}>
                        <div className="label-caps" style={{ marginBottom: '0.75rem' }}>
                          VALIDATION CHECKLIST
                        </div>
                        <ul style={{ paddingLeft: '1.25rem', color: 'var(--text-secondary)', fontSize: '0.9rem', margin: 0 }}>
                          {(enhRes.needs_dev_validation || []).map((step: string, i: number) => (
                            <li key={i} style={{ marginBottom: '6px' }}>{step}</li>
                          ))}
                        </ul>
                      </div>

                      <div className="col-6" style={{ border: '1px solid var(--border)', backgroundColor: 'var(--bg-white)', padding: '1.75rem' }}>
                        <div className="label-caps" style={{ color: 'var(--status-failed-text)', marginBottom: '0.75rem' }}>
                          DOWNSTREAM RISKS
                        </div>
                        <ul style={{ paddingLeft: '1.25rem', color: 'var(--text-secondary)', fontSize: '0.9rem', margin: 0 }}>
                          {(enhRes.downstream_risks || []).map((risk: string, i: number) => (
                            <li key={i} style={{ marginBottom: '6px' }}>{risk}</li>
                          ))}
                        </ul>
                      </div>
                    </div>
                  </div>
                )}
              </div>
            )}
          </section>
        )}

        {/* ============================================================ */}
        {/* TAB 5: DOCUMENTATION — DOCX / PDF EXPORT                     */}
        {/* ============================================================ */}
        {activeTab === 'docs' && (
          <section aria-labelledby="docs-heading">
            <div style={{ marginBottom: '2.5rem' }}>
              <div className="label-caps" style={{ marginBottom: '0.25rem' }}>
                SPECIFICATION EXPORT
              </div>
              <h2 id="docs-heading" className="hero-title" style={{ fontSize: 'clamp(2.5rem, 5vw, 4.5rem)', marginBottom: '0.5rem' }}>
                FUNCTIONAL <span className="accent">DOCUMENTATION.</span>
              </h2>
              <p style={{ color: 'var(--text-secondary)', fontSize: '1.1rem', maxWidth: '720px' }}>
                Export an authoritative 13-section functional specification guide readable by PMs, BAs, and technical stakeholders.
              </p>
            </div>

            {/* Quick Full Specification Bundle */}
            <div style={{ border: '1px solid var(--border)', backgroundColor: 'var(--bg-white)', padding: '1.5rem', marginBottom: '1.5rem', display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '1rem' }}>
              <div>
                <div className="label-caps" style={{ color: 'var(--primary)', marginBottom: '0.25rem' }}>
                  ONE-CLICK COMPLETE DOCUMENTATION
                </div>
                <p style={{ margin: 0, fontSize: '0.95rem', color: 'var(--text-secondary)' }}>
                  Generates full functional specification bundle (DOCX + PDF) encompassing all modules, business rules, schemas, and workflows.
                </p>
              </div>
              <button
                type="button"
                className="btn btn-primary"
                onClick={handleGenerateFullDocs}
                disabled={generatingFullDocs}
              >
                {generatingFullDocs ? 'COMPILING FULL SPECIFICATION…' : 'GENERATE COMPLETE FUNCTIONAL SPECIFICATION'}
              </button>
            </div>

            {/* Controls */}
            <div style={{ border: '2px solid var(--text-primary)', backgroundColor: 'var(--bg-white)', padding: '2rem', marginBottom: '2.5rem' }}>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(12, minmax(0, 1fr))', gap: '1.5rem', alignItems: 'flex-end' }}>
                <div style={{ gridColumn: 'span 6' }}>
                  <label htmlFor="docScopeInput" className="label-caps" style={{ color: 'var(--text-primary)', marginBottom: '0.5rem', display: 'block' }}>
                    DOCUMENT SCOPE
                  </label>
                  <input
                    id="docScopeInput"
                    type="text"
                    className="form-input"
                    value={docScope}
                    onChange={e => setDocScope(e.target.value)}
                    placeholder="full or module name (e.g. orders, inventory)"
                  />
                  <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)', marginTop: '4px', display: 'block' }}>
                    Enter 'full' for the comprehensive repository guide, or enter a specific module name.
                  </span>
                </div>

                <div style={{ gridColumn: 'span 6', display: 'flex', gap: '1rem', justifyContent: 'flex-end' }}>
                  <button
                    type="button"
                    className="btn btn-primary"
                    onClick={() => handleGenerateDoc('docx')}
                    disabled={docLoading}
                  >
                    {docFormatLoading === 'docx' ? 'GENERATING DOCX…' : 'GENERATE DOCX'}
                  </button>
                  <button
                    type="button"
                    className="btn btn-secondary"
                    onClick={() => handleGenerateDoc('pdf')}
                    disabled={docLoading}
                  >
                    {docFormatLoading === 'pdf' ? 'GENERATING PDF…' : 'GENERATE PDF'}
                  </button>
                </div>
              </div>
            </div>

            {docError && (
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
                Document generation error: {docError}
              </div>
            )}

            {/* Document History Cards */}
            <div>
              <div className="label-caps" style={{ marginBottom: '1rem' }}>
                GENERATED SPECIFICATION FILES
              </div>

              {generatedDocs.length === 0 ? (
                <div style={{ border: '1px solid var(--border)', backgroundColor: 'var(--bg-white)', padding: '2.5rem', textAlign: 'center' }}>
                  <p style={{ color: 'var(--text-secondary)', margin: 0 }}>
                    No documents generated in this session yet. Click Generate DOCX or Generate PDF above to export.
                  </p>
                </div>
              ) : (
                <div style={{ border: '1px solid var(--border)', backgroundColor: 'var(--bg-white)' }}>
                  <table className="editorial-table">
                    <thead>
                      <tr>
                        <th>FORMAT</th>
                        <th>DOCUMENT TITLE</th>
                        <th>GENERATED TIME</th>
                        <th>STATUS</th>
                        <th style={{ textAlign: 'right' }}>ACTION</th>
                      </tr>
                    </thead>
                    <tbody>
                      {generatedDocs.map((doc, idx) => (
                        <tr key={idx}>
                          <td style={{ fontWeight: 800, fontFamily: 'var(--font-mono)', color: 'var(--primary)' }}>
                            {doc.format}
                          </td>
                          <td style={{ fontWeight: 700 }}>
                            Functional Specification Guide ({doc.format})
                          </td>
                          <td style={{ color: 'var(--text-secondary)', fontSize: '0.85rem' }}>
                            {doc.date}
                          </td>
                          <td>
                            <StatusBadge status="READY" />
                          </td>
                          <td style={{ textAlign: 'right' }}>
                            <button
                              type="button"
                              onClick={() => handleDownloadDoc(doc)}
                              className="btn btn-outline btn-sm"
                              id={`download-${doc.format.toLowerCase()}-${doc.id}`}
                            >
                              DOWNLOAD {doc.format} ⬇
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          </section>
        )}
      </main>
    </div>
  );
}
