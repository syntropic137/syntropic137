/**
 * Hook for managing feedback list data loading and status updates.
 */

import { useCallback, useEffect, useRef, useState } from 'react';
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

  // Only the most recent load may write state. An earlier one that settles
  // late (a slow response, a filter changed mid-flight, a refresh after a
  // status change) would otherwise overwrite newer data or end `loading`
  // for a load that is still running.
  const latestLoad = useRef(0);
  // The spinner is for "nothing to show yet". Once items are on screen a
  // refresh updates them in place instead of blanking the list.
  const hasLoaded = useRef(false);

  const loadData = useCallback(async () => {
    const load = ++latestLoad.current;
    if (!hasLoaded.current) setLoading(true);
    setError(null);
    try {
      const [feedbackList, feedbackStats] = await Promise.all([
        api.listFeedback({ app: appName, status: filter === 'all' ? undefined : filter, limit: 50 }),
        api.getStats(appName),
      ]);
      if (load !== latestLoad.current) return;
      setItems(feedbackList.items);
      setStats(feedbackStats);
      hasLoaded.current = true;
    } catch (err) {
      if (load !== latestLoad.current) return;
      setError(err instanceof Error ? err.message : 'Failed to load feedback');
    } finally {
      if (load === latestLoad.current) setLoading(false);
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
