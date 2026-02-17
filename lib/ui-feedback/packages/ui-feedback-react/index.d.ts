/// <reference types="react" />

/**
 * Type declarations for @aef/ui-feedback-react
 *
 * Standalone declaration file. The `/// <reference types="react" />` directive
 * is resolved by TypeScript from the consumer's node_modules, avoiding the need
 * for react to be installed in this package's own directory.
 */

import type { FC, ReactNode } from 'react';

// =====================================================
// Domain types
// =====================================================

export type FeedbackType =
  | 'bug'
  | 'feature'
  | 'ui_ux'
  | 'performance'
  | 'question'
  | 'other';

export type Status =
  | 'open'
  | 'in_progress'
  | 'resolved'
  | 'closed'
  | 'wont_fix';

export type Priority = 'low' | 'medium' | 'high' | 'critical';

export type MediaType = 'screenshot' | 'voice_note';

export type WidgetPosition =
  | 'bottom-right'
  | 'bottom-left'
  | 'top-right'
  | 'top-left';

export interface Theme {
  primary?: string;
  primaryHover?: string;
  background?: string;
  surface?: string;
  surfaceHover?: string;
  border?: string;
  text?: string;
  textSecondary?: string;
  success?: string;
  error?: string;
  warning?: string;
}

export interface ClassNames {
  button?: string;
  modal?: string;
  overlay?: string;
  input?: string;
  select?: string;
  textarea?: string;
  badge?: string;
  pin?: string;
}

export interface LocationContext {
  url: string;
  route?: string;
  viewportWidth: number;
  viewportHeight: number;
  clickX?: number;
  clickY?: number;
  cssSelector?: string;
  xpath?: string;
  componentName?: string;
}

export interface MediaItem {
  id: string;
  media_type: MediaType;
  mime_type: string;
  file_name?: string;
  file_size?: number;
  created_at: string;
}

export interface MediaUpload {
  mediaType: MediaType;
  mimeType: string;
  fileName?: string;
  blob: Blob;
}

export interface FeedbackCreate {
  url: string;
  route?: string;
  viewport_width?: number;
  viewport_height?: number;
  click_x?: number;
  click_y?: number;
  css_selector?: string;
  xpath?: string;
  component_name?: string;
  feedback_type?: FeedbackType;
  comment?: string;
  priority?: Priority;
  app_name: string;
  app_version?: string;
  user_agent?: string;
  environment?: string;
  git_commit?: string;
  git_branch?: string;
  hostname?: string;
}

export interface FeedbackUpdate {
  status?: Status;
  priority?: Priority;
  assigned_to?: string;
  resolution_notes?: string;
  comment?: string;
}

export interface FeedbackItem {
  id: string;
  url: string;
  route?: string;
  viewport_width?: number;
  viewport_height?: number;
  click_x?: number;
  click_y?: number;
  css_selector?: string;
  xpath?: string;
  component_name?: string;
  feedback_type: FeedbackType;
  comment?: string;
  status: Status;
  priority: Priority;
  assigned_to?: string;
  resolution_notes?: string;
  app_name: string;
  app_version?: string;
  user_agent?: string;
  environment?: string;
  git_commit?: string;
  git_branch?: string;
  hostname?: string;
  created_at: string;
  updated_at: string;
  resolved_at?: string;
  media_count: number;
}

export interface FeedbackItemWithMedia extends FeedbackItem {
  media?: MediaItem[];
}

export interface FeedbackList {
  items: FeedbackItem[];
  total: number;
  page: number;
  page_size: number;
}

export interface FeedbackStats {
  total: number;
  by_status: Record<Status, number>;
  by_type: Record<FeedbackType, number>;
  by_priority: Record<Priority, number>;
  by_app: Record<string, number>;
}

// =====================================================
// Provider configuration
// =====================================================

export interface FeedbackProviderConfig {
  apiUrl: string;
  appName: string;
  appVersion?: string;
  keyboardShortcut?: string;
  theme?: Theme;
  classNames?: ClassNames;
  position?: WidgetPosition;
  disabled?: boolean;
  environment?: string;
  gitCommit?: string;
  gitBranch?: string;
  hostname?: string;
}

// =====================================================
// Component prop types
// =====================================================

export interface FeedbackProviderProps extends FeedbackProviderConfig {
  children?: ReactNode;
}

// eslint-disable-next-line @typescript-eslint/no-empty-object-type
export interface FeedbackWidgetProps {}

// =====================================================
// Components
// =====================================================

export declare const FeedbackProvider: FC<FeedbackProviderProps>;
export declare const FeedbackWidget: FC<FeedbackWidgetProps>;
