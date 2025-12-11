/**
 * TypeScript types for UI Feedback React components
 */

// =====================================================
// Enums / Constants
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

// =====================================================
// Location Context
// =====================================================

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

// =====================================================
// Media
// =====================================================

export interface MediaSummary {
  id: string;
  mediaType: MediaType;
  mimeType: string;
  fileName?: string;
  fileSize?: number;
  createdAt: string;
}

// Alias for MediaSummary - used when displaying media items
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

// =====================================================
// Feedback Items
// =====================================================

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
  // Environment context
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
  // Environment context
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

// =====================================================
// Stats
// =====================================================

export interface FeedbackStats {
  total: number;
  by_status: Record<Status, number>;
  by_type: Record<FeedbackType, number>;
  by_priority: Record<Priority, number>;
  by_app: Record<string, number>;
}

// =====================================================
// Provider Configuration
// =====================================================

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

export type WidgetPosition =
  | 'bottom-right'
  | 'bottom-left'
  | 'top-right'
  | 'top-left';

export interface FeedbackProviderConfig {
  /** Base URL for the feedback API (required) */
  apiUrl: string;
  /** Name of the application (required) */
  appName: string;
  /** Version of the application */
  appVersion?: string;
  /** Keyboard shortcut to toggle feedback mode (default: 'Ctrl+Shift+F') */
  keyboardShortcut?: string;
  /** Custom theme colors */
  theme?: Theme;
  /** Custom CSS class names */
  classNames?: ClassNames;
  /** Widget position (default: 'bottom-right') */
  position?: WidgetPosition;
  /** Disable the widget (useful for conditional rendering) */
  disabled?: boolean;
  // Environment context - for knowing where feedback came from
  /** Environment name (e.g., 'development', 'staging', 'production') */
  environment?: string;
  /** Git commit hash */
  gitCommit?: string;
  /** Git branch name */
  gitBranch?: string;
  /** Hostname where the app is running */
  hostname?: string;
}

// =====================================================
// Internal State
// =====================================================

export interface FeedbackState {
  isOpen: boolean;
  isFeedbackMode: boolean;
  locationContext: LocationContext | null;
  pendingMedia: MediaUpload[];
}

export interface FeedbackContextValue extends FeedbackState {
  config: FeedbackProviderConfig;
  openFeedbackMode: () => void;
  closeFeedbackMode: () => void;
  openModal: (context: LocationContext) => void;
  closeModal: () => void;
  addMedia: (media: MediaUpload) => void;
  removeMedia: (index: number) => void;
  clearMedia: () => void;
  submitFeedback: (data: Omit<FeedbackCreate, 'app_name' | 'app_version' | 'user_agent' | 'environment' | 'git_commit' | 'git_branch' | 'hostname'>) => Promise<FeedbackItem>;
}
