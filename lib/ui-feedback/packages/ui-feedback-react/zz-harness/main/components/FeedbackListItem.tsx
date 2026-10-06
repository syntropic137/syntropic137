/**
 * Single feedback list item card
 */

import { STATUS_COLORS, STATUS_LABELS, TYPE_EMOJI } from '../constants/statusMeta';
import type { FeedbackItem, Status } from '../types';
import { formatTimeAgo } from '../utils/formatTimeAgo';

interface FeedbackListItemProps {
  item: FeedbackItem;
  onSelect: () => void;
  onStatusChange: (id: string, status: Status) => void;
}

export function FeedbackListItem({ item, onSelect, onStatusChange }: FeedbackListItemProps) {
  return (
    <div className="ui-feedback-list-item" onClick={onSelect}>
      <div className="ui-feedback-list-item-header">
        <span className="ui-feedback-list-item-type">
          {TYPE_EMOJI[item.feedback_type] || '\u{1F4DD}'}
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
          onChange={(e) => onStatusChange(item.id, e.target.value as Status)}
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
  );
}
