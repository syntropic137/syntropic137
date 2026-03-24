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
  useMemo,
  type CSSProperties,
  type ReactNode,
} from 'react';
import { FeedbackContext } from './FeedbackContext';
import { useFeedbackApi } from './hooks/useFeedbackApi';
import { useFeedbackState } from './hooks/useFeedbackState';
import { useKeyboardShortcuts } from './hooks/useKeyboardShortcuts';
import type {
  FeedbackContextValue,
  FeedbackProviderConfig,
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

function buildCssVariables(theme: Required<Theme>): CSSProperties {
  return {
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
}

export function FeedbackProvider({
  children, apiUrl, appName, appVersion,
  keyboardShortcut = 'Ctrl+Shift+F',
  theme: customTheme, classNames, position = 'bottom-right', disabled = false,
  environment, gitCommit, gitBranch, hostname,
}: FeedbackProviderProps) {
  const api = useFeedbackApi({ apiUrl });
  const theme = useMemo(() => mergeTheme(customTheme), [customTheme]);

  const config: FeedbackProviderConfig = useMemo(
    () => ({ apiUrl, appName, appVersion, keyboardShortcut, theme: customTheme, classNames, position, disabled, environment, gitCommit, gitBranch, hostname }),
    [apiUrl, appName, appVersion, keyboardShortcut, customTheme, classNames, position, disabled, environment, gitCommit, gitBranch, hostname],
  );

  const {
    state, openFeedbackMode, closeFeedbackMode, openModal, closeModal,
    addMedia, removeMedia, clearMedia, submitFeedback,
  } = useFeedbackState({ api, appName, appVersion, environment, gitCommit, gitBranch, hostname, disabled });

  useKeyboardShortcuts({
    disabled, keyboardShortcut,
    isFeedbackMode: state.isFeedbackMode, isOpen: state.isOpen,
    openFeedbackMode, closeFeedbackMode, closeModal,
  });

  const contextValue: FeedbackContextValue = useMemo(
    () => ({ ...state, config, openFeedbackMode, closeFeedbackMode, openModal, closeModal, addMedia, removeMedia, clearMedia, submitFeedback }),
    [state, config, openFeedbackMode, closeFeedbackMode, openModal, closeModal, addMedia, removeMedia, clearMedia, submitFeedback],
  );

  return (
    <FeedbackContext.Provider value={contextValue}>
      <div style={buildCssVariables(theme)} className="ui-feedback-theme">
        {children}
      </div>
    </FeedbackContext.Provider>
  );
}
