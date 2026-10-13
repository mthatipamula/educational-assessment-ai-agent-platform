import { useState } from 'react';
import { api, num, when } from '../api';
import { Notice, ScoreBadge, Tag, useLoad } from '../components';
import type { ResponseRow } from '../types';

export default function ReviewQueue() {
  const [onlyQueue, setOnlyQueue] = useState(true);
  const [rows, error, reload] = useLoad(() => api<ResponseRow[]>('/api/responses'), [], 4000);
  const shown = (rows ?? []).filter((r) => !onlyQueue || r.needs_human_review);
  return (
    <div>
      <h1>Review queue</h1>
      <p className="muted">The scoring agent's score is advisory. Responses with low confidence, safety flags, or attempts to manipulate the scorer come here for a teacher's decision.</p>
      <div className="filters">
        <div className="segmented">
          <button className={onlyQueue ? 'active' : ''} onClick={() => setOnlyQueue(true)}>Needs review ({rows?.filter((r) => r.needs_human_review).length ?? 0})</button>
          <button className={!onlyQueue ? 'active' : ''} onClick={() => setOnlyQueue(false)}>All responses</button>
        </div>
      </div>
      <Notice>{error}</Notice>
      {shown.length === 0 && <p className="muted">{onlyQueue ? 'Nothing waiting for review.' : 'No responses yet.'}</p>}
      <div className="stack">{shown.map((r) => <ResponseCard key={r.id} r={r} onChange={reload} teacher />)}</div>
    </div>
  );
}

export function ResponseCard({ r, onChange, teacher = false }: { r: ResponseRow; onChange?: () => void; teacher?: boolean }) {
  const [score, setScore] = useState('');
  const [note, setNote] = useState('');
  const [error, setError] = useState('');
  const result = r.ai_result;
  async function save() {
    try { await api(`/api/responses/${r.id}/review`, { method: 'POST', body: { score: Number(score), note } }); onChange?.(); }
    catch (e) { setError((e as Error).message); }
  }
  return (
    <article className="card response">
      <div className="row-between">
        <div className="tags">
          {teacher && <strong>{r.student_name}</strong>}
          {r.human_score != null ? <><Tag tone="good">Teacher: {num(r.human_score)} / {num(r.max_score)}</Tag><span className="muted small">AI suggested {num(r.ai_score)}</span></>
            : <ScoreBadge score={r.ai_score} max={r.max_score} status={r.status} />}
          {r.ai_confidence != null && <span className="muted small">confidence {num(Number(r.ai_confidence) * 100, 0)}%</span>}
          {r.needs_human_review && <Tag tone="warn">Needs teacher review</Tag>}
          {r.safety?.flags?.filter((f) => f !== 'CLASSIFIER_UNAVAILABLE').map((f) => <Tag key={f} tone="bad">{f.replace('_', ' ').toLowerCase()}</Tag>)}
        </div>
        <span className="muted small">{when(r.created_at)}</span>
      </div>
      <p className="muted small">{r.stem}</p>
      <blockquote className={r.item_type === 'CODE' ? 'code' : ''}>{r.response_text}</blockquote>
      {r.review_reasons?.length > 0 && <Notice kind="warn">{r.review_reasons.join(' · ')}</Notice>}
      {result && (
        <>
          <table className="compact">
            <thead><tr><th>Criterion</th><th className="num">Points</th><th>Evidence and reasoning</th></tr></thead>
            <tbody>{result.criteria.map((c) => (
              <tr key={c.criterion}><td>{c.criterion}</td><td className="num">{num(c.points_awarded)}{c.max_points != null && ` / ${c.max_points}`}</td>
                <td><span className="evidence">{c.evidence}</span><div className="muted small">{c.reasoning}</div></td></tr>))}</tbody>
          </table>
          {result.tests && <p className="small">{result.tests.map((t) => `Test ${t.test}: ${t.passed ? 'pass' : `fail${t.error ? ` (${t.error})` : ''}`}`).join(' · ')}</p>}
          {result.feedback_for_student && <p><strong>Feedback:</strong> {result.feedback_for_student}</p>}
          {result.misconception && <p className="muted small">Misconception noted: {result.misconception}</p>}
          <p className="muted small">Scored by {result.served_by ?? result.method}</p>
        </>
      )}
      {r.human_note && <p className="small"><strong>Teacher note:</strong> {r.human_note}</p>}
      {teacher && r.status !== 'SCORING' && r.human_score == null && (
        <div className="decide">
          <input type="number" min={0} max={Number(r.max_score ?? 10)} step={0.5} placeholder={`Score (0-${num(r.max_score)})`} value={score} onChange={(e) => setScore(e.target.value)} />
          <input placeholder="Note to the student (optional)" value={note} onChange={(e) => setNote(e.target.value)} />
          <button disabled={score === ''} onClick={save}>Save teacher score</button>
        </div>
      )}
      <Notice>{error}</Notice>
    </article>
  );
}
