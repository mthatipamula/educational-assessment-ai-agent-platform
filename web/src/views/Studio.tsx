import { useEffect, useState } from 'react';
import { api, when } from '../api';
import { Notice, Spinner, Tag, useLoad } from '../components';
import { TYPE_LABEL, type AgentRun, type Item, type Standard } from '../types';
import { ItemCard } from './ItemBank';

export default function Studio() {
  const [standards] = useLoad(() => api<Standard[]>('/api/standards'), []);
  const [form, setForm] = useState({ standard_code: '', item_type: 'MULTIPLE_CHOICE', difficulty: 'MEDIUM', topic: '' });
  const [runId, setRunId] = useState<string | null>(null);
  const [error, setError] = useState('');
  useEffect(() => { if (!form.standard_code && standards?.length) setForm((f) => ({ ...f, standard_code: standards[1].code })); }, [standards, form.standard_code]);
  const [runs, , reloadRuns] = useLoad(() => api<AgentRun[]>('/api/authoring/runs'), [], 5000);

  async function start() {
    setError('');
    try {
      const { runId } = await api<{ runId: string }>('/api/authoring/runs', { method: 'POST', body: form });
      setRunId(runId); reloadRuns();
    } catch (e) { setError((e as Error).message); }
  }

  const standard = standards?.find((s) => s.code === form.standard_code);
  return (
    <div className="two-col">
      <section>
        <h1>Item studio</h1>
        <p className="muted">The authoring agent researches the standard and passages, checks for similar items, drafts an item, reviews its own draft and revises it. You approve it before any student sees it.</p>
        <div className="card form">
          <label>Learning standard
            <select value={form.standard_code} onChange={(e) => setForm({ ...form, standard_code: e.target.value })}>
              {standards?.map((s) => <option key={s.code} value={s.code}>Grade {s.grade} {s.subject}: {s.title} ({s.code})</option>)}
            </select>
          </label>
          {standard && <p className="muted small">{standard.description}</p>}
          <div className="row">
            <label>Item type
              <select value={form.item_type} onChange={(e) => setForm({ ...form, item_type: e.target.value })}>
                {Object.entries(TYPE_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
              </select>
            </label>
            <label>Difficulty
              <select value={form.difficulty} onChange={(e) => setForm({ ...form, difficulty: e.target.value })}>
                <option>EASY</option><option>MEDIUM</option><option>HARD</option>
              </select>
            </label>
          </div>
          <label>Context (optional)<input value={form.topic} maxLength={200} placeholder="e.g. a school garden, the River Cleanup passage"
            onChange={(e) => setForm({ ...form, topic: e.target.value })} /></label>
          <Notice>{error}</Notice>
          <button onClick={start} disabled={!form.standard_code}>Generate item with AI</button>
        </div>
        <h2>Recent runs</h2>
        <ul className="run-list">
          {runs?.map((r) => (
            <li key={r.id}><button className={`run ${r.id === runId ? 'selected' : ''}`} onClick={() => setRunId(r.id)}>
              <span>{TYPE_LABEL[r.input.item_type]} · {r.input.standard_code}</span>
              <RunStatus status={r.status} /><span className="muted small">{when(r.started_at)}</span>
            </button></li>
          ))}
        </ul>
      </section>
      <section>{runId ? <RunView id={runId} /> : <div className="empty card">Start a run to watch the agent work.</div>}</section>
    </div>
  );
}

const RunStatus = ({ status }: { status: AgentRun['status'] }) =>
  status === 'RUNNING' ? <Tag tone="info"><Spinner /> Running</Tag> : status === 'SUCCEEDED' ? <Tag tone="good">Draft ready</Tag> : <Tag tone="bad">Failed</Tag>;

function RunView({ id }: { id: string }) {
  const [run] = useLoad(() => api<AgentRun>(`/api/authoring/runs/${id}`), [id], 1500);
  const [items, , reloadItems] = useLoad(() => api<Item[]>('/api/items'), [run?.status]);
  if (!run) return <p className="muted">Loading…</p>;
  const item = run.output ? items?.find((i) => i.id === run.output!.item_id) : undefined;
  return (
    <div>
      <div className="row-between"><h2>Agent run</h2><RunStatus status={run.status} /></div>
      <ol className="steps">
        {run.steps.map((raw, i) => {
          const s = typeof raw === 'string' ? (() => { try { return JSON.parse(raw); } catch { return { step: raw, detail: '' }; } })() : raw;
          const detail = typeof s?.detail === 'string' ? s.detail : JSON.stringify(s?.detail ?? '') ?? '';
          return <li key={i}><strong>{s?.step ?? 'step'}</strong><code className="small">{detail.slice(0, 220)}</code></li>;
        })}
        {run.status === 'RUNNING' && <li className="muted"><Spinner /> working…</li>}
      </ol>
      {run.error && <Notice>{run.error}</Notice>}
      {item && <ItemCard item={item} onChange={reloadItems} expanded />}
    </div>
  );
}
