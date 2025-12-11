import { BrowserRouter, Route, Routes } from 'react-router-dom'
import { FeedbackProvider, FeedbackWidget } from '@aef/ui-feedback-react'

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

// Feedback API URL - defaults to localhost for dev
const FEEDBACK_API_URL = import.meta.env.VITE_FEEDBACK_API_URL || 'http://localhost:8001/api'

export function App() {
  return (
    <FeedbackProvider
      apiUrl={FEEDBACK_API_URL}
      appName="aef-dashboard"
      appVersion="0.1.0"
      environment={import.meta.env.MODE}
      gitCommit={import.meta.env.VITE_GIT_COMMIT}
      gitBranch={import.meta.env.VITE_GIT_BRANCH}
      hostname={typeof window !== 'undefined' ? window.location.hostname : undefined}
      keyboardShortcut="Ctrl+Shift+F"
      position="bottom-right"
    >
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
      <FeedbackWidget />
    </FeedbackProvider>
  )
}
