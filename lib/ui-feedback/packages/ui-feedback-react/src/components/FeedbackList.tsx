/**
 * Feedback list/tickets view component
 */

import { useCallback, useEffect, useState } from 'react';
import { useFeedbackApi } from '../hooks/useFeedbackApi';
import type { FeedbackItem, FeedbackStats, Status } from '../types';
import { FeedbackDetail } from './FeedbackDetail';

export interface FeedbackListProps {
  apiUrl: string;
  appName?: string;
  onClose: () => void;
  onSelectFeedback?: (feedback: FeedbackItem) => void;
}

const STATUS_COLORS: Record<Status, string> = {
  open: 'var(--feedback-warning)',
  in_progress: 'var(--feedback-primary)',
  resolved: 'var(--feedback-success)',
  closed: 'var(--feedback-text-secondary)',
  wont_fix: 'var(--feedback-text-secondary)',
};

const STATUS_LABELS: Record<Status, string> = {
  open: 'Open',
  in_progress: 'In Progress',
  resolved: 'Resolved',
  closed: 'Closed',
  wont_fix: "Won't Fix",
};

const TYPE_EMOJI: Record<string, string> = {
  bug: '🐛',
  feature: '✨',
  ui_ux: '🎨',
  performance: '⚡',
  question: '❓',
  other: '📝',
};

export function FeedbackList({ apiUrl, appName, onClose, onSelectFeedback }: FeedbackListProps) {
  const api = useFeedbackApi({ apiUrl });
  const [items, setItems] = useState<FeedbackItem[]>([]);
  const [stats, setStats] = useState<FeedbackStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<Status | 'all'>('all');
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const loadData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [feedbackList, feedbackStats] = await Promise.all([
        api.listFeedback({
          app: appName,
          status: filter === 'all' ? undefined : filter,
          limit: 50,
        }),
        api.getStats(appName),
      ]);
      setItems(feedbackList.items);
      setStats(feedbackStats);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load feedback');
    } finally {
      setLoading(false);
    }
  }, [api, appName, filter]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  const handleStatusChange = useCallback(
    async (id: string, newStatus: Status) => {
      try {
        await api.updateFeedback(id, { status: newStatus });
        await loadData();
      } catch (err) {
        console.error('Failed to update status:', err);
      }
    },
    [api, loadData]
  );

  return (
    <div className="ui-feedback-modal-overlay" onClick={onClose}>
      <div
        className="ui-feedback-modal ui-feedback-list-modal"
        onClick={(e) => e.stopPropagation()}
        style={{ maxWidth: '700px' }}
      >
        {/* Header */}
        <div className="ui-feedback-modal-header">
          <div className="ui-feedback-modal-header-content">
            <h2 className="ui-feedback-modal-title">Feedback Tickets</h2>
            {stats && (
              <p className="ui-feedback-modal-subtitle">
                {stats.total} total • {stats.by_status.open} open
              </p>
            )}
          </div>
          <button
            type="button"
            className="ui-feedback-modal-close"
            onClick={onClose}
            aria-label="Close"
          >
            <CloseIcon />
          </button>
        </div>

        {/* Stats bar */}
        {stats && stats.total > 0 && (
          <div className="ui-feedback-stats-bar">
            <button
              className={`ui-feedback-stat-btn ${filter === 'all' ? 'ui-feedback-stat-btn--active' : ''}`}
              onClick={() => setFilter('all')}
            >
              All ({stats.total})
            </button>
            <button
              className={`ui-feedback-stat-btn ${filter === 'open' ? 'ui-feedback-stat-btn--active' : ''}`}
              onClick={() => setFilter('open')}
              style={{ '--stat-color': STATUS_COLORS.open } as React.CSSProperties}
            >
              Open ({stats.by_status.open})
            </button>
            <button
              className={`ui-feedback-stat-btn ${filter === 'in_progress' ? 'ui-feedback-stat-btn--active' : ''}`}
              onClick={() => setFilter('in_progress')}
              style={{ '--stat-color': STATUS_COLORS.in_progress } as React.CSSProperties}
            >
              In Progress ({stats.by_status.in_progress})
            </button>
            <button
              className={`ui-feedback-stat-btn ${filter === 'resolved' ? 'ui-feedback-stat-btn--active' : ''}`}
              onClick={() => setFilter('resolved')}
              style={{ '--stat-color': STATUS_COLORS.resolved } as React.CSSProperties}
            >
              Resolved ({stats.by_status.resolved})
            </button>
            <button
              className={`ui-feedback-stat-btn ${filter === 'closed' ? 'ui-feedback-stat-btn--active' : ''}`}
              onClick={() => setFilter('closed')}
              style={{ '--stat-color': STATUS_COLORS.closed } as React.CSSProperties}
            >
              Closed ({stats.by_status.closed})
            </button>
            <button
              className={`ui-feedback-stat-btn ${filter === 'wont_fix' ? 'ui-feedback-stat-btn--active' : ''}`}
              onClick={() => setFilter('wont_fix')}
              style={{ '--stat-color': STATUS_COLORS.wont_fix } as React.CSSProperties}
            >
              Won't Fix ({stats.by_status.wont_fix})
            </button>
          </div>
        )}

        {/* Body */}
        <div className="ui-feedback-modal-body" style={{ padding: 0 }}>
          {loading ? (
            <div className="ui-feedback-list-loading">
              <div className="ui-feedback-spinner" />
              Loading feedback...
            </div>
          ) : error ? (
            <div className="ui-feedback-list-error">
              <span className="ui-feedback-error">{error}</span>
              <button className="ui-feedback-btn ui-feedback-btn--secondary" onClick={loadData}>
                Retry
              </button>
            </div>
          ) : items.length === 0 ? (
            <div className="ui-feedback-list-empty">
              <EmptyIcon />
              <p>No feedback yet</p>
              <span>Click the feedback button to leave your first feedback!</span>
            </div>
          ) : (
            <div className="ui-feedback-list">
              {items.map((item) => (
                <div
                  key={item.id}
                  className="ui-feedback-list-item"
                  onClick={() => {
                    setSelectedId(item.id);
                    onSelectFeedback?.(item);
                  }}
                >
                  <div className="ui-feedback-list-item-header">
                    <span className="ui-feedback-list-item-type">
                      {TYPE_EMOJI[item.feedback_type] || '📝'}
                    </span>
                    <span className="ui-feedback-list-item-url">{new URL(item.url).pathname}</span>
                    <span
                      className="ui-feedback-list-item-status"
                      style={{ backgroundColor: STATUS_COLORS[item.status] }}
                    >
                      {STATUS_LABELS[item.status]}
                    </span>
                  </div>
                  <div className="ui-feedback-list-item-body">
                    {item.comment ? (
                      <p className="ui-feedback-list-item-comment">{item.comment}</p>
                    ) : (
                      <p className="ui-feedback-list-item-comment ui-feedback-list-item-comment--empty">
                        No comment
                      </p>
                    )}
                  </div>
                  <div className="ui-feedback-list-item-footer">
                    <span className="ui-feedback-list-item-meta">
                      {item.component_name && (
                        <span className="ui-feedback-list-item-component">
                          &lt;{item.component_name}&gt;
                        </span>
                      )}
                      <span className="ui-feedback-list-item-time">
                        {formatTimeAgo(new Date(item.created_at))}
                      </span>
                    </span>
                    <select
                      className="ui-feedback-list-item-status-select"
                      value={item.status}
                      onChange={(e) => handleStatusChange(item.id, e.target.value as Status)}
                      onClick={(e) => e.stopPropagation()}
                    >
                      <option value="open">Open</option>
                      <option value="in_progress">In Progress</option>
                      <option value="resolved">Resolved</option>
                      <option value="closed">Closed</option>
                      <option value="wont_fix">Won't Fix</option>
                    </select>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="ui-feedback-modal-footer">
          <button
            type="button"
            className="ui-feedback-btn ui-feedback-btn--secondary"
            onClick={loadData}
          >
            <RefreshIcon />
            Refresh
          </button>
          <button
            type="button"
            className="ui-feedback-btn ui-feedback-btn--primary"
            onClick={onClose}
          >
            Close
          </button>
        </div>
      </div>

      {/* Detail view overlay */}
      {selectedId && (
        <FeedbackDetail
          apiUrl={apiUrl}
          feedbackId={selectedId}
          onClose={() => setSelectedId(null)}
          onStatusChange={() => loadData()}
        />
      )}
    </div>
  );
}

// Utility function
function formatTimeAgo(date: Date): string {
  const seconds = Math.floor((Date.now() - date.getTime()) / 1000);

  if (seconds < 60) return 'just now';
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
  if (seconds < 604800) return `${Math.floor(seconds / 86400)}d ago`;
  return date.toLocaleDateString();
}

// Icons
function CloseIcon() {
  return (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <line x1="18" y1="6" x2="6" y2="18" />
      <line x1="6" y1="6" x2="18" y2="18" />
    </svg>
  );
}

function EmptyIcon() {
  return (
    <svg
      width="48"
      height="48"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      opacity="0.5"
    >
      <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
      <line x1="9" y1="9" x2="15" y2="9" />
      <line x1="9" y1="13" x2="13" y2="13" />
    </svg>
  );
}

function RefreshIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <path d="M21 2v6h-6" />
      <path d="M3 12a9 9 0 0 1 15-6.7L21 8" />
      <path d="M3 22v-6h6" />
      <path d="M21 12a9 9 0 0 1-15 6.7L3 16" />
    </svg>
  );
}
