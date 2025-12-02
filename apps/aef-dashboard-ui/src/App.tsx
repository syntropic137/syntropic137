import { BrowserRouter, Route, Routes } from 'react-router-dom'

import { Layout } from './components'
import {
  ArtifactDetail,
  ArtifactList,
  Dashboard,
  SessionDetail,
  SessionList,
  WorkflowDetail,
  WorkflowList,
} from './pages'

export function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Layout />}>
          <Route index element={<Dashboard />} />
          <Route path="workflows" element={<WorkflowList />} />
          <Route path="workflows/:workflowId" element={<WorkflowDetail />} />
          <Route path="sessions" element={<SessionList />} />
          <Route path="sessions/:sessionId" element={<SessionDetail />} />
          <Route path="artifacts" element={<ArtifactList />} />
          <Route path="artifacts/:artifactId" element={<ArtifactDetail />} />
        </Route>
      </Routes>
    </BrowserRouter>
  )
}
