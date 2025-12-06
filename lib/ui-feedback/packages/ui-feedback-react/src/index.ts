/**
 * UI Feedback React - Contextual feedback widget for React applications
 *
 * @packageDocumentation
 */

// Styles
import './styles.css';

// Types
export type {
  ClassNames,
  FeedbackContextValue,
  FeedbackCreate,
  FeedbackItem,
  FeedbackItemWithMedia,
  FeedbackList as FeedbackListResponse,
  FeedbackProviderConfig,
  FeedbackState,
  FeedbackStats,
  FeedbackType,
  FeedbackUpdate,
  LocationContext,
  MediaItem,
  MediaSummary,
  MediaType,
  MediaUpload,
  Priority,
  Status,
  Theme,
  WidgetPosition,
} from './types';

// Components
export { FeedbackProvider } from './FeedbackProvider';
export { FeedbackWidget } from './FeedbackWidget';
export { FeedbackList } from './components/FeedbackList';
export { FeedbackDetail } from './components/FeedbackDetail';

// Hooks
export { useFeedback } from './FeedbackContext';
export { useFeedbackApi } from './hooks/useFeedbackApi';
export { useElementInfo } from './hooks/useElementInfo';
export { useScreenCapture } from './hooks/useScreenCapture';
export { useVoiceRecorder, formatDuration } from './hooks/useVoiceRecorder';

// Utilities (for advanced usage)
export { getCssSelector, getXPath, getDataAttribute } from './utils/getElementPath';
export { getReactComponentName, getComponentInfo } from './utils/getReactComponent';
export { captureFullPage, captureArea, blobToDataUrl, resizeImage } from './utils/captureArea';
