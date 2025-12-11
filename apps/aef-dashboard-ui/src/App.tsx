import { BrowserRouter, Route, Routes } from 'react-router-dom'
// TODO: Re-enable once ui-feedback-react submodule is built
// import { FeedbackProvider, FeedbackWidget } from '@aef/ui-feedback-react'

import { Layout } from './components'
import {
  ArtifactDetail,
  ArtifactList,
  Dashboard,
  ExecutionDetail,
  ExecutionList,
  SessionDetail,
  SessionList,
  WorkflowDetail,
  WorkflowList,
  WorkflowRuns,
} from './pages'

// TODO: Re-enable once ui-feedback-react submodule is built
// Feedback API URL - defaults to localhost for dev
// const FEEDBACK_API_URL = import.meta.env.VITE_FEEDBACK_API_URL || 'http://localhost:8001/api'

export function App() {
  return (
    // TODO: Re-wrap with FeedbackProvider once ui-feedback-react submodule is built
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
        </Route>
      </Routes>
    </BrowserRouter>
  )
}
