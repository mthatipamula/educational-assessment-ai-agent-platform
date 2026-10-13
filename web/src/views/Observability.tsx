import { api, num, when } from '../api';
import { Notice, Tag, useLoad } from '../components';

interface Obs {
  modelCalls: { role: string; provider: string; model: string; calls: number; failures: number; p50_ms: number | null; p95_ms: number | null;
                input_tokens: number; output_tokens: number; cost_usd: string }[];
  safety: { category: string; action: string; events: number }[];
  recentFailures: { created_at: string; role: string; provider: string; model: string; error: string }[];
  reviewQueue: number;
  providers: { provider: string; available: boolean; retryInSeconds: number; lastError: string }[];
  embeddingProviders: { provider: string; available: boolean; lastError: string }[];
}

export default function Observability() {
  const [o, error] = useLoad(() => api<Obs>('/api/observability'), [], 5000);
  if (!o) return <Notice>{error}</Notice>;
  const calls = o.modelCalls.reduce((s, c) => s + c.calls, 0);
  const failures = o.modelCalls.reduce((s, c) => s + c.failures, 0);
  const cost = o.modelCalls.reduce((s, c) => s + Number(c.cost_usd), 0);
  const fallbacks = o.modelCalls.filter((c) => c.provider === 'bedrock').reduce((s, c) => s + c.failures, 0);
  return (
    <div>
      <h1>Observability <span className="muted small">(last 24 hours)</span></h1>
      <div className="kpis">
        <div className="kpi"><span>Model calls</span><strong>{calls}</strong></div>
        <div className={`kpi ${failures ? 'warn' : ''}`}><span>Failed calls</span><strong>{failures}</strong></div>
        <div className="kpi"><span>Fell back from Bedrock</span><strong>{fallbacks}</strong></div>
        <div className="kpi"><span>Estimated cost</span><strong>${cost.toFixed(3)}</strong></div>
        <div className={`kpi ${o.reviewQueue ? 'warn' : ''}`}><span>Human review queue</span><strong>{o.reviewQueue}</strong></div>
      </div>
      <h2>Providers</h2>
      <div className="tags">
        {o.providers.map((p) => <Tag key={p.provider} tone={p.available ? 'good' : 'bad'}>Claude via {p.provider}: {p.available ? 'available' : `skipped (${p.retryInSeconds}s)`}</Tag>)}
        {o.embeddingProviders.map((p) => <Tag key={p.provider} tone={p.available ? 'good' : 'bad'}>Embeddings via {p.provider}: {p.available ? 'available' : 'skipped'}</Tag>)}
      </div>
      <h2>Calls by agent and model</h2>
      <div className="table-wrap"><table>
        <thead><tr><th>Agent</th><th>Provider</th><th>Model</th><th className="num">Calls</th><th className="num">Failed</th><th className="num">p50 ms</th><th className="num">p95 ms</th><th className="num">Tokens in / out</th><th className="num">Cost</th></tr></thead>
        <tbody>{o.modelCalls.map((c, i) => (
          <tr key={i}><td>{c.role}</td><td>{c.provider}</td><td className="mono small">{c.model}</td><td className="num">{c.calls}</td>
            <td className="num">{c.failures || ''}</td><td className="num">{num(c.p50_ms, 0)}</td><td className="num">{num(c.p95_ms, 0)}</td>
            <td className="num">{c.input_tokens.toLocaleString()} / {c.output_tokens.toLocaleString()}</td><td className="num">${Number(c.cost_usd).toFixed(4)}</td></tr>))}</tbody>
      </table></div>
      <div className="two-col even">
        <section>
          <h2>Safety events</h2>
          {o.safety.length === 0 ? <p className="muted">None.</p> : (
            <table className="compact"><tbody>{o.safety.map((s) => (
              <tr key={s.category + s.action}><td>{s.category.replace('_', ' ').toLowerCase()}</td><td><Tag tone={s.action === 'ESCALATED' ? 'bad' : 'warn'}>{s.action.toLowerCase()}</Tag></td><td className="num">{s.events}</td></tr>))}</tbody></table>
          )}
        </section>
        <section>
          <h2>Recent failures</h2>
          {o.recentFailures.length === 0 ? <p className="muted">None.</p> : (
            <ul className="failures">{o.recentFailures.map((f, i) => (
              <li key={i}><span className="muted small">{when(f.created_at)} · {f.role} · {f.provider}</span><div className="small mono">{f.error.slice(0, 160)}</div></li>))}</ul>
          )}
        </section>
      </div>
    </div>
  );
}
