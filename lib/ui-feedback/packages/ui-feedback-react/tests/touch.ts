/**
 * Synthetic touch events with real touchend semantics: the lifted finger is
 * in `changedTouches` and `touches` is empty. jsdom has no Touch constructor,
 * so the lists are attached as plain properties.
 */

interface Point { clientX: number; clientY: number }

function touchEvent(type: 'touchstart' | 'touchend', point: Point, stillDown: boolean): Event {
  const e = new Event(type, { bubbles: true, cancelable: true });
  Object.defineProperty(e, 'changedTouches', { value: [point] });
  Object.defineProperty(e, 'touches', { value: stillDown ? [point] : [] });
  return e;
}

/** Dispatches a finger down at `from` and up at `to` on `el`; returns the touchend. */
export function touch(el: Element, from: Point, to: Point = from): Event {
  el.dispatchEvent(touchEvent('touchstart', from, true));
  const end = touchEvent('touchend', to, false);
  el.dispatchEvent(end);
  return end;
}
