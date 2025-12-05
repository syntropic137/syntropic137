/**
 * React Context for UI Feedback
 */

import { createContext, useContext } from 'react';
import type { FeedbackContextValue } from './types';

export const FeedbackContext = createContext<FeedbackContextValue | null>(null);

export function useFeedback(): FeedbackContextValue {
  const context = useContext(FeedbackContext);
  if (!context) {
    throw new Error('useFeedback must be used within a FeedbackProvider');
  }
  return context;
}
