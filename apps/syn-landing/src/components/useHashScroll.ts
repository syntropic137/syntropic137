import { useEffect } from "react";

/** How long after mount the target is held in place while late content (fonts, elements) settles (ms). */
const SETTLE = 1500;
/** Any of these means the user has taken over, so the target is no longer held. */
const USER_INPUT = ["wheel", "touchstart", "keydown", "pointerdown"] as const;

function target(): Element | null {
  const id = decodeURIComponent(window.location.hash.slice(1));
  return id ? document.getElementById(id) : null;
}

/**
 * Scrolls to the URL's #fragment once the page has rendered. The browser's own
 * jump runs before React has mounted the sections, so a deep link such as
 * /#observability would otherwise stay at the top. Late layout shifts re-align
 * it until SETTLE has passed or the user scrolls, taps or types.
 */
export function useHashScroll(): void {
  useEffect(() => {
    if (!target()) return;
    const align = () => target()?.scrollIntoView({ behavior: "instant", block: "start" });
    const ro = new ResizeObserver(align);
    let timer = 0;
    let held = true;
    const stop = () => {
      held = false;
      ro.disconnect();
      window.clearTimeout(timer);
      for (const e of USER_INPUT) window.removeEventListener(e, stop);
    };

    align();
    ro.observe(document.body);
    for (const e of USER_INPUT) window.addEventListener(e, stop, { passive: true });
    timer = window.setTimeout(stop, SETTLE);
    void document.fonts?.ready.then(() => held && align());
    return stop;
  }, []);
}
