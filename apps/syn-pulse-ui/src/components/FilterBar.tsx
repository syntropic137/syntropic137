import { useEffect, useState, useCallback } from 'react'
import { listOrganizations, listSystems, listRepos } from '../api/client'
import type { OrgSummary, SystemSummary, RepoSummary } from '../types'

interface FilterBarProps {
  onFilterChange: (filter: {
    organization_id?: string
    system_id?: string
    repo_id?: string
  }) => void
}

function Select({ label, value, options, onChange }: {
  label: string
  value: string
  options: { value: string; label: string }[]
  onChange: (v: string) => void
}) {
  return (
    <div className="flex flex-col gap-1">
      <label className="text-xs font-medium" style={{ color: 'var(--color-text-muted)' }}>
        {label}
      </label>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="px-3 py-1.5 rounded-lg text-sm border-0 outline-none"
        style={{
          background: 'var(--color-surface-elevated)',
          color: 'var(--color-text-primary)',
          border: '1px solid var(--color-border)',
        }}
      >
        <option value="">All</option>
        {options.map((o) => (
          <option key={o.value} value={o.value}>{o.label}</option>
        ))}
      </select>
    </div>
  )
}

export function FilterBar({ onFilterChange }: FilterBarProps) {
  const [orgs, setOrgs] = useState<OrgSummary[]>([])
  const [systems, setSystems] = useState<SystemSummary[]>([])
  const [repos, setRepos] = useState<RepoSummary[]>([])

  const [orgId, setOrgId] = useState('')
  const [systemId, setSystemId] = useState('')
  const [repoId, setRepoId] = useState('')

  useEffect(() => {
    listOrganizations().then(setOrgs).catch(() => {/* no orgs available */})
  }, [])

  const handleOrgChange = useCallback((id: string) => {
    setOrgId(id)
    setSystems([])
    setSystemId('')
    setRepos([])
    setRepoId('')
    onFilterChange({ organization_id: id || undefined })
    if (id) {
      listSystems(id).then(setSystems).catch(() => {/* no systems */})
    }
  }, [onFilterChange])

  const handleSystemChange = useCallback((id: string) => {
    setSystemId(id)
    setRepos([])
    setRepoId('')
    onFilterChange({
      organization_id: orgId || undefined,
      system_id: id || undefined,
    })
    if (id) {
      listRepos(id).then(setRepos).catch(() => {/* no repos */})
    }
  }, [orgId, onFilterChange])

  const handleRepoChange = useCallback((id: string) => {
    setRepoId(id)
    onFilterChange({
      organization_id: orgId || undefined,
      system_id: systemId || undefined,
      repo_id: id || undefined,
    })
  }, [orgId, systemId, onFilterChange])

  return (
    <div className="flex flex-wrap gap-4">
      <Select
        label="Organization"
        value={orgId}
        options={orgs.map((o) => ({ value: o.organization_id, label: o.name }))}
        onChange={handleOrgChange}
      />
      {orgId && (
        <Select
          label="System"
          value={systemId}
          options={systems.map((s) => ({ value: s.system_id, label: s.name }))}
          onChange={handleSystemChange}
        />
      )}
      {systemId && (
        <Select
          label="Repository"
          value={repoId}
          options={repos.map((r) => ({ value: r.repo_id, label: r.full_name }))}
          onChange={handleRepoChange}
        />
      )}
    </div>
  )
}
