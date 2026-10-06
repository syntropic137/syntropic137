import { createRoot } from 'react-dom/client';
// @ts-ignore - WIDGET is aliased per build to the before/after source tree
import { FeedbackProvider, FeedbackWidget } from 'WIDGET';

function ExecutionRow({ id, status }: { id: string; status: string }) {
  return (
    <a href={`#/executions/${id}`} style={{ display: 'block', padding: '14px 16px', borderBottom: '1px solid #333', color: '#ddd', textDecoration: 'none' }}>
      <strong>exec-{id}</strong> <span style={{ float: 'right' }}>{status}</span>
    </a>
  );
}

function App() {
  return (
    <div style={{ fontFamily: 'sans-serif', background: '#111', minHeight: '100vh' }}>
      <h1 style={{ color: '#fff', padding: 16, margin: 0, fontSize: 20 }}>Executions</h1>
      {['a1b2', 'c3d4', 'e5f6', 'g7h8'].map((id, i) => <ExecutionRow key={id} id={id} status={['running', 'completed', 'failed', 'completed'][i]} />)}
    </div>
  );
}

createRoot(document.getElementById('root')!).render(
  <FeedbackProvider apiUrl="http://127.0.0.1:9/api" appName="harness"><App /><FeedbackWidget /></FeedbackProvider>,
);
