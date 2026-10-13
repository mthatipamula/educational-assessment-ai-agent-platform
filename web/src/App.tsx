import { useState } from 'react';
import { api, loadUser, PERSONAS, saveUser, type User } from './api';
import { useLoad } from './components';
import Evals from './views/Evals';
import ItemBank from './views/ItemBank';
import Observability from './views/Observability';
import Practice from './views/Practice';
import ReviewQueue from './views/ReviewQueue';
import Studio from './views/Studio';

type View = 'studio' | 'bank' | 'review' | 'evals' | 'obs' | 'practice' | 'work';
const TEACHER_NAV: [View, string][] = [['studio', 'Item studio'], ['bank', 'Item bank'], ['review', 'Review queue'], ['evals', 'Evaluations'], ['obs', 'Observability']];
const STUDENT_NAV: [View, string][] = [['practice', 'Practice'], ['work', 'My work']];

interface Status { llm: { provider: string; available: boolean; lastError: string }[]; embeddings: { provider: string; available: boolean }[] }

export default function App() {
  const [user, setUser] = useState<User | null>(loadUser());
  const [view, setView] = useState<View>(user?.role === 'TEACHER' ? 'studio' : 'practice');
  if (!user) return <SignIn onPick={(u) => { saveUser(u); setUser(u); setView(u.role === 'TEACHER' ? 'studio' : 'practice'); }} />;
  const nav = user.role === 'TEACHER' ? TEACHER_NAV : STUDENT_NAV;
  return (
    <div>
      <header className="topbar">
        <div className="brand"><img src="/favicon.svg" alt="" /> Assessment Studio</div>
        <nav aria-label="Main">{nav.map(([id, label]) => (
          <button key={id} className={view === id ? 'active' : ''} onClick={() => setView(id)}>{label}</button>))}
        </nav>
        <ProviderChips />
        <div className="who"><span>{user.name}</span><button className="link" onClick={() => { saveUser(null); setUser(null); }}>Switch user</button></div>
      </header>
      <main>
        {view === 'studio' && <Studio />}
        {view === 'bank' && <ItemBank />}
        {view === 'review' && <ReviewQueue />}
        {view === 'evals' && <Evals />}
        {view === 'obs' && <Observability />}
        {view === 'practice' && <Practice user={user} />}
        {view === 'work' && <Practice user={user} workOnly />}
      </main>
    </div>
  );
}

/** Which model providers are serving right now: Bedrock first, Anthropic API as fallback. */
function ProviderChips() {
  const [status] = useLoad(() => api<Status>('/api/status'), [], 15000);
  if (!status) return null;
  const label: Record<string, string> = { bedrock: 'Bedrock', anthropic: 'Anthropic API', voyage: 'Voyage' };
  return (
    <div className="chips" title="Claude and embedding providers, in fallback order">
      <span className="muted small">Claude:</span>
      {status.llm.map((p) => <span key={p.provider} className={`chip ${p.available ? 'up' : 'down'}`} title={p.lastError || 'available'}>{label[p.provider]}</span>)}
      <span className="muted small">Embeddings:</span>
      {status.embeddings.map((p) => <span key={p.provider} className={`chip ${p.available ? 'up' : 'down'}`}>{p.provider === 'bedrock' ? 'Titan' : label[p.provider]}</span>)}
    </div>
  );
}

function SignIn({ onPick }: { onPick: (u: User) => void }) {
  return (
    <div className="signin">
      <div className="signin-card">
        <div className="brand big"><img src="/favicon.svg" alt="" /> Assessment Studio</div>
        <p className="muted">AI agents that help teachers write standards-aligned items, score student work with human oversight, and tutor students without giving away answers.</p>
        <h2>Sign in as (local demo)</h2>
        <div className="personas">
          {PERSONAS.map((p) => (
            <button key={p.key} className="persona" onClick={() => onPick(p)}><strong>{p.name}</strong><span>{p.detail}</span></button>
          ))}
        </div>
        <p className="fineprint">Demo data only: synthetic students and items. No real student information.</p>
      </div>
    </div>
  );
}
