import { cleanup, render, renderHook, screen, act } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { FeedbackProvider } from '../src/FeedbackProvider';
import { FeedbackWidget } from '../src/FeedbackWidget';
import { useElementInfo } from '../src/hooks/useElementInfo';
import { TAP_SLOP_PX, useFeedbackModeClick } from '../src/hooks/useFeedbackModeClick';
import type { LocationContext } from '../src/types';
import { touch } from './touch';

afterEach(() => {
  cleanup();
  document.body.innerHTML = '';
});

function setup() {
  document.body.innerHTML = '<nav><a id="link" href="#/elsewhere">Executions</a></nav>';
  const link = document.getElementById('link')!;
  const linkActivated = vi.fn();
  link.addEventListener('click', linkActivated);

  const openModal = vi.fn<(c: LocationContext) => void>();
  const openQuickFeedback = vi.fn();
  renderHook(() => {
    const { captureFromElement } = useElementInfo();
    useFeedbackModeClick({ isFeedbackMode: true, captureFromElement, openModal, openQuickFeedback });
  });
  return { link, linkActivated, openModal, openQuickFeedback };
}

describe('pin mode, touch', () => {
  it('pins the tapped element and cancels the tap', () => {
    const { link, openModal, openQuickFeedback } = setup();

    const end = touch(link, { clientX: 30, clientY: 12 });

    expect(openQuickFeedback).not.toHaveBeenCalled();
    expect(openModal).toHaveBeenCalledTimes(1);
    const ctx = openModal.mock.calls[0][0];
    expect(document.querySelector(ctx.cssSelector!)).toBe(link);
    expect(ctx).toMatchObject({ clickX: 30, clickY: 12, elementLabel: 'a "Executions"' });
    // Cancelling touchend is what suppresses the synthetic click on the link.
    expect(end.defaultPrevented).toBe(true);
  });

  it('treats a moved touch as a scroll, not a pick', () => {
    const { link, openModal, openQuickFeedback } = setup();

    const end = touch(link, { clientX: 30, clientY: 12 }, { clientX: 30, clientY: 12 + TAP_SLOP_PX + 30 });

    expect(openModal).not.toHaveBeenCalled();
    expect(openQuickFeedback).not.toHaveBeenCalled();
    expect(end.defaultPrevented).toBe(false);
  });
});

describe('pin mode, mouse', () => {
  it('pins the clicked element at the pointer and does not activate it', () => {
    const { link, linkActivated, openModal } = setup();

    link.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true, clientX: 7, clientY: 9 }));

    expect(linkActivated).not.toHaveBeenCalled();
    expect(openModal.mock.calls[0][0]).toMatchObject({ clickX: 7, clickY: 9, elementLabel: 'a "Executions"' });
  });
});

function ExecutionRow() {
  return <button type="button" aria-label="Cancel execution">X</button>;
}

describe('FeedbackWidget', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ total: 0, by_status: {}, by_type: {}, by_priority: {} }))));
  });

  it('shows what a tap pinned and lets the user re-pick', async () => {
    render(
      <FeedbackProvider apiUrl="http://feedback.test/api" appName="test">
        <ExecutionRow />
        <FeedbackWidget />
      </FeedbackProvider>,
    );

    await act(async () => { screen.getByTitle(/feedback/i).click(); });
    await act(async () => { screen.getByText(/pin to element/i).click(); });

    const target = screen.getByRole('button', { name: 'Cancel execution' });
    await act(async () => { touch(target, { clientX: 5, clientY: 5 }); });

    const label = 'button "Cancel execution" \u00b7 <ExecutionRow>';
    expect(screen.getByText(label)).toBeTruthy();
    expect(document.querySelector('.ui-feedback-pinned-highlight')?.getAttribute('data-label')).toBe(label);
    // The marker shares the overlay's stacking context and comes before the
    // modal, so it paints over the backdrop but never over the modal's controls.
    const overlayChildren = [...document.querySelector('.ui-feedback-modal-overlay')!.children].map((el) => el.className);
    expect(overlayChildren).toEqual(['ui-feedback-pinned-highlight', 'ui-feedback-pin', 'ui-feedback-modal']);

    await act(async () => { screen.getByRole('button', { name: 'Re-pick' }).click(); });
    expect(screen.queryByText('Leave Feedback')).toBeNull();
    expect(document.body.classList.contains('ui-feedback-mode-active')).toBe(true);
  });
});
