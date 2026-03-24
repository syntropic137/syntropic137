/**
 * Feedback list/tickets view component
 */

import { useEffect } from 'react';
import { useFeedbackListData } from '../hooks/useFeedbackListData';
import type { FeedbackItem, Status } from '../types';
import { CloseIcon, EmptyIcon, RefreshIcon } from './icons';
import { FeedbackDetail } from './FeedbackDetail';
import { FeedbackListItem } from './FeedbackListItem';
import { StatusFilterBar } from './StatusFilterBar';

export interface FeedbackListProps {
  apiUrl: string;
  appName?: string;
  onClose: () => void;
  onSelectFeedback?: (feedback: FeedbackItem) => void;
}

export function FeedbackList({ apiUrl, appName, onClose, onSelectFeedback }: FeedbackListProps) {
  const data = useFeedbackListData(apiUrl, appName);

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        if (data.selectedId) data.setSelectedId(null);
        else onClose();
      }
    };
    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [onClose, data.selectedId, data.setSelectedId]);

  return (
    <div className="ui-feedback-modal-overlay" onClick={onClose}>
      <div className="ui-feedback-modal ui-feedback-list-modal" onClick={(e) => e.stopPropagation()} style={{ maxWidth: '700px' }}>
        <div className="ui-feedback-modal-header">
          <div className="ui-feedback-modal-header-content">
            <h2 className="ui-feedback-modal-title">Feedback Tickets</h2>
            {data.stats && <p className="ui-feedback-modal-subtitle">{data.stats.total} total {'\u2022'} {data.stats.by_status.open} open</p>}
          </div>
          <button type="button" className="ui-feedback-modal-close" onClick={onClose} aria-label="Close"><CloseIcon /></button>
        </div>

        {data.stats && data.stats.total > 0 && <StatusFilterBar stats={data.stats} filter={data.filter} onFilterChange={data.setFilter} />}

        <div className="ui-feedback-modal-body" style={{ padding: 0 }}>
          <FeedbackListBody
            loading={data.loading} error={data.error} items={data.items}
            loadData={data.loadData} onSelect={(item) => { data.setSelectedId(item.id); onSelectFeedback?.(item); }}
            onStatusChange={data.handleStatusChange}
          />
        </div>

        <div className="ui-feedback-modal-footer">
          <button type="button" className="ui-feedback-btn ui-feedback-btn--secondary" onClick={data.loadData}><RefreshIcon /> Refresh</button>
          <button type="button" className="ui-feedback-btn ui-feedback-btn--primary" onClick={onClose}>Close</button>
        </div>
      </div>

      {data.selectedId && <FeedbackDetail apiUrl={apiUrl} feedbackId={data.selectedId} onClose={() => data.setSelectedId(null)} onStatusChange={() => data.loadData()} />}
    </div>
  );
}

function FeedbackListBody({ loading, error, items, loadData, onSelect, onStatusChange }: {
  loading: boolean; error: string | null; items: FeedbackItem[];
  loadData: () => void; onSelect: (item: FeedbackItem) => void;
  onStatusChange: (id: string, status: Status) => void;
}) {
  if (loading) {
    return <div className="ui-feedback-list-loading"><div className="ui-feedback-spinner" /> Loading feedback...</div>;
  }
  if (error) {
    return (
      <div className="ui-feedback-list-error">
        <span className="ui-feedback-error">{error}</span>
        <button className="ui-feedback-btn ui-feedback-btn--secondary" onClick={loadData}>Retry</button>
      </div>
    );
  }
  if (items.length === 0) {
    return <div className="ui-feedback-list-empty"><EmptyIcon /><p>No feedback yet</p><span>Click the feedback button to leave your first feedback!</span></div>;
  }
  return (
    <div className="ui-feedback-list">
      {items.map((item) => (
        <FeedbackListItem key={item.id} item={item} onSelect={() => onSelect(item)} onStatusChange={onStatusChange} />
      ))}
    </div>
  );
}
