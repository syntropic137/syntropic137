/**
 * Pin-to-element driven the way a phone drives it: touchstart + touchend,
 * no hover and no mouse events. Asserts on what the user sees (the pinned
 * label in the modal) and what reaches the API, not on hook internals.
 */
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { FeedbackProvider } from '../FeedbackProvider';
import { FeedbackWidget } from '../FeedbackWidget';

type Point = { clientX: number; clientY: number };

function touch(target: Element, type: 'touchstart' | 'touchend', point: Point): TouchEvent {
  const event = new TouchEvent(type, { bubbles: true, cancelable: true });
  const list = [{ ...point, target }];
  // A real touchend has the lifted finger in changedTouches and NOT in touches.
  Object.defineProperty(event, 'touches', { value: type === 'touchend' ? [] : list });
  Object.defineProperty(event, 'changedTouches', { value: list });
  target.dispatchEvent(event);
  return event;
}

function tap(target: Element, at: Point = { clientX: 50, clientY: 60 }, end: Point = at): TouchEvent {
  touch(target, 'touchstart', at);
  let ended!: TouchEvent;
  act(() => { ended = touch(target, 'touchend', end); });
  return ended;
}

const fetchMock = vi.fn();

function renderPage() {
  const onLinkClick = vi.fn((e: React.MouseEvent) => e.preventDefault());
  render(
    <FeedbackProvider apiUrl="http://feedback.test/api" appName="test-app">
      <nav>
        <a href="/executions" onClick={onLinkClick}>Executions</a>
        <button type="button" aria-label="Cancel execution">x</button>
      </nav>
      <FeedbackWidget />
    </FeedbackProvider>,
  );
  return { onLinkClick };
}

function enterPinMode() {
  fireEvent.click(screen.getByTitle(/^Feedback/));
  fireEvent.click(screen.getByText('Pin to Element'));
}

beforeEach(() => {
  fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
    const body = url.includes('/stats')
      ? { total: 0, by_status: {}, by_type: {}, by_priority: {} }
      : { id: 'fb-1', ...JSON.parse(String(init?.body ?? '{}')) };
    return new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } });
  });
  vi.stubGlobal('fetch', fetchMock);
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  fetchMock.mockReset();
});

describe('tap to pin', () => {
  it('pins the tapped element and says which element it was', () => {
    renderPage();
    enterPinMode();

    const ended = tap(screen.getByText('Executions'));

    expect(ended.defaultPrevented).toBe(true);
    expect(screen.getByText('a "Executions"')).toBeTruthy();
    expect(screen.getByText(/Pinned to/)).toBeTruthy();
  });

  it('uses the accessible name for an icon button', () => {
    renderPage();
    enterPinMode();

    tap(screen.getByLabelText('Cancel execution'));

    expect(screen.getByText('button "Cancel execution"')).toBeTruthy();
  });

  it('sends the tapped element\'s selector and tap coordinates with the feedback', async () => {
    renderPage();
    enterPinMode();
    tap(screen.getByText('Executions'), { clientX: 31, clientY: 42 });

    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'wrong link' } });
    await act(async () => { fireEvent.click(screen.getByText('Submit Feedback')); });

    const create = fetchMock.mock.calls.find(([url, init]) => String(url).endsWith('/feedback') && init?.method === 'POST');
    expect(create).toBeDefined();
    const sent = JSON.parse(String(create![1].body));
    expect(sent.css_selector).toContain('a');
    expect(sent.xpath).toBeTruthy();
    expect(sent.click_x).toBe(31);
    expect(sent.click_y).toBe(42);
    expect(sent).not.toHaveProperty('elementLabel');
  });

  it('does not activate the tapped link while pinning', () => {
    const { onLinkClick } = renderPage();
    enterPinMode();

    const link = screen.getByText('Executions');
    const ended = tap(link);
    // A browser only synthesizes the click when touchend was not cancelled;
    // and if one arrives anyway, pin mode is over and nothing is re-pinned.
    if (!ended.defaultPrevented) fireEvent.click(link);

    expect(onLinkClick).not.toHaveBeenCalled();
  });

  it('treats a touch that moved as a scroll and pins nothing', () => {
    renderPage();
    enterPinMode();

    const ended = tap(screen.getByText('Executions'), { clientX: 50, clientY: 300 }, { clientX: 52, clientY: 120 });

    expect(ended.defaultPrevented).toBe(false);
    expect(screen.queryByText(/Pinned to/)).toBeNull();
    expect(screen.getByText(/tap any element to pin feedback/)).toBeTruthy();
  });

  it('re-pick returns to pin mode, keeps the draft, and pins the new element', () => {
    renderPage();
    enterPinMode();
    tap(screen.getByText('Executions'));
    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'my draft' } });

    fireEvent.click(screen.getByText('Re-pick'));
    expect(screen.queryByText(/Pinned to/)).toBeNull();
    expect(screen.getByText(/tap any element to pin feedback/)).toBeTruthy();

    tap(screen.getByLabelText('Cancel execution'));
    expect(screen.getByText('button "Cancel execution"')).toBeTruthy();
    expect((screen.getByRole('textbox') as HTMLTextAreaElement).value).toBe('my draft');
  });
});

describe('desktop click to pin', () => {
  it('still pins on click and shows the same label', () => {
    renderPage();
    enterPinMode();

    fireEvent.click(screen.getByText('Executions'), { clientX: 10, clientY: 20 });

    expect(screen.getByText('a "Executions"')).toBeTruthy();
  });
});
