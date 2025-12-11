/**
 * Type declarations for @aef/ui-feedback-react
 *
 * This module is resolved by Vite at runtime from lib/ui-feedback.
 * These declarations allow TypeScript to compile without errors.
 */
declare module '@aef/ui-feedback-react' {
  import type { FC, ReactNode } from 'react'

  export interface FeedbackProviderProps {
    /** Base URL for the feedback API (required) */
    apiUrl: string
    /** Children to render inside the provider */
    children: ReactNode
    /** Name of the application (required) */
    appName: string
    /** Version of the application */
    appVersion?: string
    /** Keyboard shortcut to toggle feedback mode (default: 'Ctrl+Shift+F') */
    keyboardShortcut?: string
    /** Widget position (default: 'bottom-right') */
    position?: 'bottom-right' | 'bottom-left' | 'top-right' | 'top-left'
    /** Disable the widget */
    disabled?: boolean
    // Environment context - for knowing where feedback came from
    /** Environment name (e.g., 'development', 'staging', 'production') */
    environment?: string
    /** Git commit hash */
    gitCommit?: string
    /** Git branch name */
    gitBranch?: string
    /** Hostname where the app is running */
    hostname?: string
  }

  export const FeedbackProvider: FC<FeedbackProviderProps>

  export interface FeedbackWidgetProps {
    // Widget is configured via FeedbackProvider, no props needed
  }

  export const FeedbackWidget: FC<FeedbackWidgetProps>
}
