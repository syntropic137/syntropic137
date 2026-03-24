/**
 * Status filter bar for feedback list view
 */

import { STATUS_COLORS } from '../constants/statusMeta';
import type { FeedbackStats, Status } from '../types';

const FILTERS: Array<{ value: Status | 'all'; label: string }> = [
  { value: 'all', label: 'All' },
  { value: 'open', label: 'Open' },
  { value: 'in_progress', label: 'In Progress' },
  { value: 'resolved', label: 'Resolved' },
  { value: 'closed', label: 'Closed' },
  { value: 'wont_fix', label: "Won't Fix" },
];

interface StatusFilterBarProps {
  stats: FeedbackStats;
  filter: Status | 'all';
  onFilterChange: (filter: Status | 'all') => void;
}

function getCount(stats: FeedbackStats, value: Status | 'all'): number {
  return value === 'all' ? stats.total : stats.by_status[value];
}

export function StatusFilterBar({ stats, filter, onFilterChange }: StatusFilterBarProps) {
  return (
    <div className="ui-feedback-stats-bar">
      {FILTERS.map(({ value, label }) => (
        <button
          key={value}
          className={`ui-feedback-stat-btn ${filter === value ? 'ui-feedback-stat-btn--active' : ''}`}
          onClick={() => onFilterChange(value)}
          style={value !== 'all' ? { '--stat-color': STATUS_COLORS[value] } as React.CSSProperties : undefined}
        >
          {label} ({getCount(stats, value)})
        </button>
      ))}
    </div>
  );
}
