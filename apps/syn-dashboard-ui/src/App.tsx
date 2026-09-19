import { BrowserRouter, Route, Routes } from 'react-router-dom'

import { FeedbackMount, Layout } from './components'
import {
  ArtifactDetail,
  ArtifactList,
  Dashboard,
  ExecutionDetail,
  ExecutionList,
  Insights,
  SessionDetail,
  SessionList,
  TriggerDetail,
  TriggerList,
  WorkflowDetail,
  WorkflowList,
  WorkflowRuns,
} from './pages'

export function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Layout />}>
          <Route index element={<Dashboard />} />
          <Route path="workflows" element={<WorkflowList />} />
          <Route path="workflows/:workflowId" element={<WorkflowDetail />} />
          <Route path="workflows/:workflowId/runs" element={<WorkflowRuns />} />
          <Route path="executions" element={<ExecutionList />} />
          <Route path="executions/:executionId" element={<ExecutionDetail />} />
          <Route path="sessions" element={<SessionList />} />
          <Route path="sessions/:sessionId" element={<SessionDetail />} />
          <Route path="artifacts" element={<ArtifactList />} />
          <Route path="artifacts/:artifactId" element={<ArtifactDetail />} />
          <Route path="triggers" element={<TriggerList />} />
          <Route path="triggers/:triggerId" element={<TriggerDetail />} />
          <Route path="insights" element={<Insights />} />
          <Route path="insights/*" element={<Insights />} />
        </Route>
      </Routes>
      {/*
        One mount for the whole app, so the floating button and the
        Ctrl+Shift+F hotkey work on every page (#105, ADR-016). A sibling of
        <Routes>, not a wrapper: it is fixed-position, and it needs
        useLocation() to know what the current page is about, which only
        works inside the router.
      */}
      <FeedbackMount />
    </BrowserRouter>
  )
}
