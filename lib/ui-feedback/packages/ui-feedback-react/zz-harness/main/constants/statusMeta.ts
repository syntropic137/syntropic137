/**
 * Shared status, type, and priority metadata constants
 */

import type { FeedbackType, Priority, Status } from '../types';

export const STATUS_COLORS: Record<Status, string> = {
  open: 'var(--feedback-warning)',
  in_progress: 'var(--feedback-primary)',
  resolved: 'var(--feedback-success)',
  closed: 'var(--feedback-text-secondary)',
  wont_fix: 'var(--feedback-text-secondary)',
};

export const STATUS_LABELS: Record<Status, string> = {
  open: 'Open',
  in_progress: 'In Progress',
  resolved: 'Resolved',
  closed: 'Closed',
  wont_fix: "Won't Fix",
};

export const TYPE_EMOJI: Record<string, string> = {
  bug: '\u{1F41B}',
  feature: '\u2728',
  ui_ux: '\u{1F3A8}',
  performance: '\u26A1',
  question: '\u2753',
  other: '\u{1F4DD}',
};

export const TYPE_LABELS: Record<string, string> = {
  bug: '\u{1F41B} Bug Report',
  feature: '\u2728 Feature Request',
  ui_ux: '\u{1F3A8} UI/UX Feedback',
  performance: '\u26A1 Performance Issue',
  question: '\u2753 Question',
  other: '\u{1F4DD} Other',
};

export const PRIORITY_COLORS: Record<string, string> = {
  low: '#6b7280',
  medium: '#f59e0b',
  high: '#ef4444',
  critical: '#dc2626',
};

export const FEEDBACK_TYPES: { value: FeedbackType; label: string; emoji: string; color: string }[] = [
  { value: 'bug', label: 'Bug', emoji: '\u{1F41B}', color: '#ef4444' },
  { value: 'feature', label: 'Feature', emoji: '\u2728', color: '#8b5cf6' },
  { value: 'ui_ux', label: 'UI/UX', emoji: '\u{1F3A8}', color: '#3b82f6' },
  { value: 'performance', label: 'Perf', emoji: '\u26A1', color: '#f59e0b' },
  { value: 'question', label: 'Question', emoji: '\u2753', color: '#6b7280' },
  { value: 'other', label: 'Other', emoji: '\u{1F4DD}', color: '#6b7280' },
];

export const PRIORITIES: { value: Priority; label: string; color: string }[] = [
  { value: 'low', label: 'Low', color: '#6b7280' },
  { value: 'medium', label: 'Medium', color: '#f59e0b' },
  { value: 'high', label: 'High', color: '#ef4444' },
  { value: 'critical', label: 'Critical', color: '#dc2626' },
];
