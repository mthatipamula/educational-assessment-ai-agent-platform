import { useEffect, useRef, useState } from 'react';
import { api, type User } from '../api';
import { Notice, ScoreBadge, Spinner, Tag, useLoad } from '../components';
import { TYPE_LABEL, type Item, type ResponseRow } from '../types';
import { ResponseCard } from './ReviewQueue';

interface TutorState { hint_level: number; attempts: number; misconceptions: string[]; last_score?: number; max_score?: number }
interface Memory { id: number; kind: string; content: string; created_at: string }

export default function Practice({ user, workOnly = false }: { user: User; workOnly?: boolean }) {
  const [items] = useLoad(() => api<Item[]>('/api/items'), []);
  const [responses, , reloadResponses] = useLoad(() => api<ResponseRow[]>('/api/responses'), [], 3000);
  const [memory] = useLoad(() => api<Memory[]>('/api/memory'), [], 10000);
  const [selected, setSelected] = useState<string | null>(null);
  useEffect(() => { if (!selected && items?.length) setSelected(items[0].id); }, [items, selected]);

  if (workOnly) {
    return (
      <div>
        <h1>My work</h1>
        <div className="stack">{responses?.map((r) => <ResponseCard key={r.id} r={r} />)}</div>
        {responses?.length === 0 && <p className="muted">Nothing submitted yet.</p>}
        <h2>What your tutor remembers about you</h2>
        {memory?.length ? <ul className="plain">{memory.map((m) => <li key={m.id}><Tag>{m.kind.toLowerCase()}</Tag> {m.content}</li>)}</ul>
          : <p className="muted">Nothing yet. Notes appear as you work with the tutor.</p>}
      </div>
    );
  }

  const item = items?.find((i) => i.id === selected);
  return (
    <div className="practice">
      <aside className="item-list">
        <h2>Practice</h2>
        {items?.map((i) => {
          const latest = responses?.find((r) => r.item_id === i.id);
          return (
            <button key={i.id} className={`item-pick ${i.id === selected ? 'selected' : ''}`} onClick={() => setSelected(i.id)}>
              <span className="small muted">{TYPE_LABEL[i.item_type]} · {i.standard_title}</span>
              <span className="clamp">{i.stem}</span>
              {latest && <ScoreBadge score={latest.human_score ?? latest.ai_score} max={latest.max_score} status={latest.status} />}
            </button>
          );
        })}
      </aside>
      {item && <Workspace key={item.id} item={item} user={user} responses={responses?.filter((r) => r.item_id === item.id) ?? []} onSubmitted={reloadResponses} />}
    </div>
  );
}

function Workspace({ item, user, responses, onSubmitted }: { item: Item; user: User; responses: ResponseRow[]; onSubmitted: () => void }) {
  const [answer, setAnswer] = useState(item.item_type === 'CODE' ? 'def solve(scores):\n    ' : '');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [testRun, setTestRun] = useState<{ results: { test: number; passed: boolean; expected?: unknown; actual?: unknown; error?: string }[]; error?: string } | null>(null);

  async function submit() {
    setBusy(true); setError('');
    try { await api('/api/responses', { method: 'POST', body: { item_id: item.id, response_text: answer } }); onSubmitted(); }
    catch (e) { setError((e as Error).message); }
    setBusy(false);
  }
  async function runTests() {
    setTestRun(null);
    try { setTestRun(await api('/api/sandbox/run', { method: 'POST', body: { item_id: item.id, code: answer } })); }
    catch (e) { setError((e as Error).message); }
  }

  return (
    <div className="workspace">
      <section className="card">
        <div className="tags"><Tag>{TYPE_LABEL[item.item_type]}</Tag><Tag tone="info">{item.standard_code}</Tag></div>
        <p className="stem big">{item.stem}</p>
        {item.item_type === 'MULTIPLE_CHOICE' && item.choices && (
          <div className="choice-list">{item.choices.map((c, i) => {
            const letter = String.fromCharCode(65 + i);
            return <label key={letter} className={`choice ${answer === letter ? 'selected' : ''}`}>
              <input type="radio" name="choice" checked={answer === letter} onChange={() => setAnswer(letter)} /> <strong>{letter}.</strong> {c}</label>;
          })}</div>
        )}
        {item.item_type === 'CONSTRUCTED_RESPONSE' && (
          <textarea rows={6} value={answer} onChange={(e) => setAnswer(e.target.value)} placeholder="Write your answer and explain your thinking…" />
        )}
        {item.item_type === 'CODE' && (
          <>
            <textarea className="code" rows={9} spellCheck={false} value={answer} onChange={(e) => setAnswer(e.target.value)} />
            <button className="secondary" onClick={runTests}>Run tests (sandbox)</button>
            {testRun && <ul className="tests">{testRun.results.map((t) => (
              <li key={t.test} className={t.passed ? 'pass' : 'fail'}>{t.passed ? '✅' : '❌'} Test {t.test}{t.error ? `: ${t.error}` : !t.passed ? `: expected ${JSON.stringify(t.expected)}, got ${JSON.stringify(t.actual)}` : ''}</li>))}</ul>}
          </>
        )}
        <Notice>{error}</Notice>
        <button disabled={!answer.trim() || busy} onClick={submit}>{busy ? 'Submitting…' : 'Submit answer'}</button>
        {responses.slice(0, 2).map((r) => <ResponseCard key={r.id} r={r} />)}
      </section>
      <Tutor item={item} user={user} />
    </div>
  );
}

function Tutor({ item }: { item: Item; user: User }) {
  const [session, , reload] = useLoad(() => api<{ state: TutorState; transcript: { role: string; text: string }[] }>(`/api/tutor/${item.id}`), [item.id]);
  const [message, setMessage] = useState('');
  const [busy, setBusy] = useState(false);
  const [meta, setMeta] = useState<{ servedBy: string; toolsUsed: string[]; safetyFlags: string[] } | null>(null);
  const [error, setError] = useState('');
  const endRef = useRef<HTMLDivElement>(null);
  // Braces matter: scrollIntoView returns a Promise in newer browsers, and an effect must not return one.
  useEffect(() => { endRef.current?.scrollIntoView({ block: 'nearest' }); }, [session, busy]);

  async function send() {
    const text = message.trim();
    if (!text) return;
    setBusy(true); setError(''); setMessage('');
    try { setMeta(await api(`/api/tutor/${item.id}/messages`, { method: 'POST', body: { message: text } })); reload(); }
    catch (e) { setError((e as Error).message); setMessage(text); }
    setBusy(false);
  }
  const state = session?.state;
  return (
    <aside className="card tutor">
      <div className="row-between"><h2>AI tutor</h2>{state && <span className="muted small">Hint level {state.hint_level}/3</span>}</div>
      <p className="muted small">Your tutor gives hints and asks questions. It won't tell you the answer.</p>
      <div className="chat">
        {session?.transcript.length === 0 && <p className="muted small">Ask for help anytime, for example "I don't know where to start."</p>}
        {session?.transcript.map((t, i) => <div key={i} className={`bubble ${t.role}`}>{t.text}</div>)}
        {busy && <div className="bubble tutor muted"><Spinner /> thinking…</div>}
        <div ref={endRef} />
      </div>
      <Notice>{error}</Notice>
      <form className="send" onSubmit={(e) => { e.preventDefault(); void send(); }}>
        <input value={message} onChange={(e) => setMessage(e.target.value)} placeholder="Ask your tutor…" maxLength={2000} disabled={busy} />
        <button disabled={busy || !message.trim()}>Send</button>
      </form>
      {meta && <p className="muted tiny">Served by {meta.servedBy}{meta.toolsUsed.length > 0 && ` · tools: ${meta.toolsUsed.join(', ')}`}{meta.safetyFlags.length > 0 && ` · safety: ${meta.safetyFlags.join(', ')}`}</p>}
      {state?.misconceptions && state.misconceptions.length > 0 && <p className="muted tiny">Shared notes: {state.misconceptions.slice(-2).join('; ')}</p>}
    </aside>
  );
}
