/**
 * Hook for managing feedback list data loading and status updates.
 */

import { useCallback, useEffect, useState } from 'react';
import type { FeedbackItem, FeedbackStats, Status } from '../types';
import { useFeedbackApi } from './useFeedbackApi';

export interface UseFeedbackListDataResult {
  items: FeedbackItem[];
  stats: FeedbackStats | null;
  loading: boolean;
  error: string | null;
  filter: Status | 'all';
  setFilter: (f: Status | 'all') => void;
  selectedId: string | null;
  setSelectedId: (id: string | null) => void;
  loadData: () => Promise<void>;
  handleStatusChange: (id: string, newStatus: Status) => Promise<void>;
}

export function useFeedbackListData(apiUrl: string, appName?: string): UseFeedbackListDataResult {
  const api = useFeedbackApi({ apiUrl });
  const [items, setItems] = useState<FeedbackItem[]>([]);
  const [stats, setStats] = useState<FeedbackStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<Status | 'all'>('all');
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const loadData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [feedbackList, feedbackStats] = await Promise.all([
        api.listFeedback({ app: appName, status: filter === 'all' ? undefined : filter, limit: 50 }),
        api.getStats(appName),
      ]);
      setItems(feedbackList.items);
      setStats(feedbackStats);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load feedback');
    } finally {
      setLoading(false);
    }
  }, [api, appName, filter]);

  useEffect(() => { loadData(); }, [loadData]);

  const handleStatusChange = useCallback(
    async (id: string, newStatus: Status) => {
      try {
        await api.updateFeedback(id, { status: newStatus });
        await loadData();
      } catch (err) {
        console.error('Failed to update status:', err);
      }
    },
    [api, loadData],
  );

  return { items, stats, loading, error, filter, setFilter, selectedId, setSelectedId, loadData, handleStatusChange };
}
