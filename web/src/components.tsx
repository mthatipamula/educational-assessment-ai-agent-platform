import { useEffect, useState, type ReactNode } from 'react';

export function useLoad<T>(load: () => Promise<T>, deps: unknown[], pollMs = 0): [T | null, string, () => void] {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState('');
  const [tick, setTick] = useState(0);
  useEffect(() => {
    let alive = true;
    const run = () => load().then((d) => alive && (setData(d), setError('')), (e: Error) => alive && setError(e.message));
    run();
    const t = pollMs ? setInterval(run, pollMs) : undefined;
    return () => { alive = false; if (t) clearInterval(t); };
  }, [...deps, tick]); // eslint-disable-line react-hooks/exhaustive-deps
  return [data, error, () => setTick((n) => n + 1)];
}

export function Notice({ kind = 'error', children }: { kind?: 'error' | 'ok' | 'info' | 'warn'; children: ReactNode }) {
  return children ? <div className={`notice ${kind}`} role={kind === 'error' ? 'alert' : 'status'}>{children}</div> : null;
}

export const Tag = ({ children, tone = '' }: { children: ReactNode; tone?: string }) => <span className={`tag ${tone}`}>{children}</span>;

export const Spinner = () => <span className="spinner" aria-hidden />;

export function ScoreBadge({ score, max, status }: { score: string | number | null; max: string | number | null; status?: string }) {
  if (score == null && status === 'NEEDS_REVIEW') return <Tag tone="warn">With teacher</Tag>;
  if (score == null || max == null) return <Tag tone="info"><Spinner /> Scoring</Tag>;
  const ratio = Number(score) / Math.max(1, Number(max));
  return <Tag tone={ratio >= 0.75 ? 'good' : ratio >= 0.4 ? 'warn' : 'bad'}>{Number(score).toString()} / {Number(max).toString()}</Tag>;
}
