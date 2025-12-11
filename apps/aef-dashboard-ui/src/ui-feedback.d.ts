/**
 * Type declarations for @aef/ui-feedback-react
 *
 * This module is resolved by Vite at runtime from lib/ui-feedback.
 * These declarations allow TypeScript to compile without errors.
 */
declare module '@aef/ui-feedback-react' {
  import type { FC, ReactNode } from 'react'

  export interface FeedbackProviderProps {
    apiUrl: string
    children: ReactNode
    source?: string
    metadata?: Record<string, unknown>
    appName?: string
    appVersion?: string
    keyboardShortcut?: string
    position?: string
  }

  export const FeedbackProvider: FC<FeedbackProviderProps>

  export interface FeedbackWidgetProps {
    position?: 'bottom-right' | 'bottom-left' | 'top-right' | 'top-left'
    primaryColor?: string
  }

  export const FeedbackWidget: FC<FeedbackWidgetProps>
}
