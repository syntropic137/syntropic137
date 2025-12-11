/**
 * FeedbackProvider - Context provider for UI Feedback
 *
 * Wraps your application to enable the feedback widget.
 *
 * @example
 * ```tsx
 * <FeedbackProvider
 *   apiUrl="http://localhost:8001/api"
 *   appName="my-app"
 *   appVersion="1.0.0"
 * >
 *   <App />
 * </FeedbackProvider>
 * ```
 */

import {
  useCallback,
  useEffect,
  useMemo,
  useState,
  type CSSProperties,
  type ReactNode,
} from 'react';
import { FeedbackContext } from './FeedbackContext';
import { useFeedbackApi } from './hooks/useFeedbackApi';
import type {
  FeedbackContextValue,
  FeedbackCreate,
  FeedbackItem,
  FeedbackProviderConfig,
  FeedbackState,
  LocationContext,
  MediaUpload,
  Theme,
} from './types';

export interface FeedbackProviderProps extends FeedbackProviderConfig {
  children: ReactNode;
}

const DEFAULT_THEME: Required<Theme> = {
  primary: '#6366f1',
  primaryHover: '#4f46e5',
  background: '#1e1e2e',
  surface: '#2a2a3e',
  surfaceHover: '#3a3a4e',
  border: '#3a3a4e',
  text: '#ffffff',
  textSecondary: '#a0a0b0',
  success: '#22c55e',
  error: '#ef4444',
  warning: '#f59e0b',
};

function mergeTheme(custom?: Theme): Required<Theme> {
  return { ...DEFAULT_THEME, ...custom };
}

export function FeedbackProvider({
  children,
  apiUrl,
  appName,
  appVersion,
  keyboardShortcut = 'Ctrl+Shift+F',
  theme: customTheme,
  classNames,
  position = 'bottom-right',
  disabled = false,
  // Environment context
  environment,
  gitCommit,
  gitBranch,
  hostname,
}: FeedbackProviderProps) {
  const [state, setState] = useState<FeedbackState>({
    isOpen: false,
    isFeedbackMode: false,
    locationContext: null,
    pendingMedia: [],
  });

  const api = useFeedbackApi({ apiUrl });
  const theme = useMemo(() => mergeTheme(customTheme), [customTheme]);

  // Config object for context
  const config: FeedbackProviderConfig = useMemo(
    () => ({
      apiUrl,
      appName,
      appVersion,
      keyboardShortcut,
      theme: customTheme,
      classNames,
      position,
      disabled,
      environment,
      gitCommit,
      gitBranch,
      hostname,
    }),
    [apiUrl, appName, appVersion, keyboardShortcut, customTheme, classNames, position, disabled, environment, gitCommit, gitBranch, hostname]
  );

  // State management functions
  const openFeedbackMode = useCallback(() => {
    if (disabled) return;
    setState((prev) => ({ ...prev, isFeedbackMode: true }));
  }, [disabled]);

  const closeFeedbackMode = useCallback(() => {
    setState((prev) => ({ ...prev, isFeedbackMode: false }));
  }, []);

  const openModal = useCallback((context: LocationContext) => {
    setState((prev) => ({
      ...prev,
      isOpen: true,
      isFeedbackMode: false,
      locationContext: context,
    }));
  }, []);

  const closeModal = useCallback(() => {
    setState((prev) => ({
      ...prev,
      isOpen: false,
      locationContext: null,
      pendingMedia: [],
    }));
  }, []);

  const addMedia = useCallback((media: MediaUpload) => {
    setState((prev) => ({
      ...prev,
      pendingMedia: [...prev.pendingMedia, media],
    }));
  }, []);

  const removeMedia = useCallback((index: number) => {
    setState((prev) => ({
      ...prev,
      pendingMedia: prev.pendingMedia.filter((_, i) => i !== index),
    }));
  }, []);

  const clearMedia = useCallback(() => {
    setState((prev) => ({ ...prev, pendingMedia: [] }));
  }, []);

  const submitFeedback = useCallback(
    async (
      data: Omit<FeedbackCreate, 'app_name' | 'app_version' | 'user_agent' | 'environment' | 'git_commit' | 'git_branch' | 'hostname'>
    ): Promise<FeedbackItem> => {
      // Create feedback item with environment context
      const feedbackData: FeedbackCreate = {
        ...data,
        app_name: appName,
        app_version: appVersion,
        user_agent: typeof navigator !== 'undefined' ? navigator.userAgent : undefined,
        environment,
        git_commit: gitCommit,
        git_branch: gitBranch,
        hostname,
      };

      const item = await api.createFeedback(feedbackData);

      // Upload any pending media
      for (const media of state.pendingMedia) {
        await api.uploadMedia(item.id, media);
      }

      // Clear state after successful submission
      closeModal();

      return item;
    },
    [api, appName, appVersion, environment, gitCommit, gitBranch, hostname, state.pendingMedia, closeModal]
  );

  // Keyboard shortcut handler
  useEffect(() => {
    if (disabled) return;

    const handleKeyDown = (e: KeyboardEvent) => {
      // Parse shortcut like "Ctrl+Shift+F"
      const parts = keyboardShortcut.split('+').map((p) => p.toLowerCase().trim());
      const key = parts.pop();

      const modifiers = {
        ctrl: parts.includes('ctrl'),
        shift: parts.includes('shift'),
        alt: parts.includes('alt'),
        meta: parts.includes('meta') || parts.includes('cmd'),
      };

      const match =
        e.key.toLowerCase() === key &&
        e.ctrlKey === modifiers.ctrl &&
        e.shiftKey === modifiers.shift &&
        e.altKey === modifiers.alt &&
        e.metaKey === modifiers.meta;

      if (match) {
        e.preventDefault();
        if (state.isFeedbackMode) {
          closeFeedbackMode();
        } else if (state.isOpen) {
          closeModal();
        } else {
          openFeedbackMode();
        }
      }

      // Escape to close
      if (e.key === 'Escape') {
        if (state.isFeedbackMode) {
          closeFeedbackMode();
        } else if (state.isOpen) {
          closeModal();
        }
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [
    disabled,
    keyboardShortcut,
    state.isFeedbackMode,
    state.isOpen,
    openFeedbackMode,
    closeFeedbackMode,
    closeModal,
  ]);

  // Context value
  const contextValue: FeedbackContextValue = useMemo(
    () => ({
      ...state,
      config,
      openFeedbackMode,
      closeFeedbackMode,
      openModal,
      closeModal,
      addMedia,
      removeMedia,
      clearMedia,
      submitFeedback,
    }),
    [
      state,
      config,
      openFeedbackMode,
      closeFeedbackMode,
      openModal,
      closeModal,
      addMedia,
      removeMedia,
      clearMedia,
      submitFeedback,
    ]
  );

  // CSS custom properties for theming
  const cssVariables: CSSProperties = {
    '--feedback-primary': theme.primary,
    '--feedback-primary-hover': theme.primaryHover,
    '--feedback-background': theme.background,
    '--feedback-surface': theme.surface,
    '--feedback-surface-hover': theme.surfaceHover,
    '--feedback-border': theme.border,
    '--feedback-text': theme.text,
    '--feedback-text-secondary': theme.textSecondary,
    '--feedback-success': theme.success,
    '--feedback-error': theme.error,
    '--feedback-warning': theme.warning,
  } as CSSProperties;

  return (
    <FeedbackContext.Provider value={contextValue}>
      <div style={cssVariables} className="ui-feedback-root">
        {children}
      </div>
    </FeedbackContext.Provider>
  );
}
