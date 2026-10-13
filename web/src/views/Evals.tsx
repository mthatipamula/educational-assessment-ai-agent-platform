import { useState } from 'react';
import { api, when } from '../api';
import { Notice, Spinner, Tag, useLoad } from '../components';

interface EvalRun { id: string; suite: string; status: string; metrics: Record<string, unknown> | null; cases: Record<string, unknown>[] | null; error: string | null; started_at: string }

const SUITES = [
  { id: 'safety', title: 'Safety red-team', what: 'Prompt injection, personal information, crisis language and harassment, plus benign answers that must not be flagged.' },
  { id: 'scoring', title: 'Scoring agreement', what: 'AI scores vs human scores on golden responses: exact/adjacent agreement, MAE and quadratic weighted kappa.' },
  { id: 'tutor', title: 'Tutor answer leaks', what: 'Students pressure the tutor for answers; an LLM judge checks for leaks and rates the pedagogy.' },
  { id: 'authoring', title: 'Item quality', what: 'The authoring agent writes items; an independent LLM judge reviews them against a checklist.' },
];

const LABEL: Record<string, string> = {
  exactAgreement: 'Exact agreement', adjacentAgreement: 'Within 1 point', meanAbsoluteError: 'Mean abs. error',
  quadraticWeightedKappa: 'Quadratic weighted kappa', humanReviewRate: 'Sent to human review', injectionRoutedToHuman: 'Injections routed to humans',
  detectionRate: 'Detection rate', falsePositiveRate: 'False positives', selfHarmEscalated: 'Crisis escalated',
  leakRateAfterGuard: 'Leak rate', leaksCaughtByGuard: 'Leaks caught by guard', meanPedagogyScore: 'Pedagogy (1-5)',
  passRate: 'Pass rate', meanQuality: 'Mean quality (1-5)', cases: 'Cases',
};

const fmt = (k: string, v: unknown) =>
  typeof v === 'boolean' ? (v ? 'Yes' : 'No') : typeof v === 'number' && /Rate|Agreement/.test(k) ? `${Math.round(v * 100)}%` : String(v ?? '-');

export default function Evals() {
  const [runs, error, reload] = useLoad(() => api<EvalRun[]>('/api/evals'), [], 3000);
  const [open, setOpen] = useState<string | null>(null);
  const [msg, setMsg] = useState('');
  async function start(suite: string) {
    try { await api(`/api/evals/${suite}`, { method: 'POST' }); setMsg(''); reload(); } catch (e) { setMsg((e as Error).message); }
  }
  const latest = (suite: string) => runs?.find((r) => r.suite === suite);
  return (
    <div>
      <h1>Evaluations</h1>
      <p className="muted">Golden datasets run against the real agents. Run them after every prompt or model change. Each run calls Claude, so it costs a few cents.</p>
      <Notice>{error || msg}</Notice>
      <div className="suite-grid">
        {SUITES.map((s) => {
          const r = latest(s.id);
          return (
            <article key={s.id} className="card suite">
              <div className="row-between"><h2>{s.title}</h2>
                {r && (r.status === 'RUNNING' ? <Tag tone="info"><Spinner /> Running</Tag> : r.status === 'SUCCEEDED' ? <Tag tone="good">{when(r.started_at)}</Tag> : <Tag tone="bad">Failed</Tag>)}</div>
              <p className="muted small">{s.what}</p>
              {r?.metrics && (
                <dl className="metrics">{Object.entries(r.metrics).map(([k, v]) => (
                  <div key={k}><dt>{LABEL[k] ?? k}</dt><dd>{fmt(k, v)}</dd></div>))}</dl>
              )}
              {r?.error && <Notice>{r.error}</Notice>}
              <div className="row">
                <button onClick={() => start(s.id)} disabled={r?.status === 'RUNNING'}>Run</button>
                {r?.cases && <button className="secondary" onClick={() => setOpen(open === r.id ? null : r.id)}>{open === r.id ? 'Hide cases' : 'Cases'}</button>}
              </div>
              {open === r?.id && r?.cases && (
                <table className="compact"><tbody>{r.cases.map((c, i) => (
                  <tr key={i}><td>{c.pass ? '✅' : '❌'}</td><td><strong>{String(c.id)}</strong></td>
                    <td className="small">{JSON.stringify(Object.fromEntries(Object.entries(c).filter(([k]) => !['id', 'pass', 'reply'].includes(k))))}</td></tr>))}</tbody></table>
              )}
            </article>
          );
        })}
      </div>
    </div>
  );
}
