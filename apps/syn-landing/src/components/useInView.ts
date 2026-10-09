import { useEffect, useState, type RefObject } from "react";

/** The page has to have painted for this long before an entrance starts (ms since navigation). */
const FIRST_BEAT = 600;
/** And an entrance reached by scrolling waits this long, so it starts once the user has arrived. */
const BEAT = 120;
const STEPS = Array.from({ length: 21 }, (_, i) => i / 20);

/**
 * True once `ref` is substantially on screen, and from then on (plays once
 * per page load). "Substantially" is `share` of the element's height, or of
 * the viewport's when the element is taller, so an element wider than the
 * screen (the phone hero city) still counts. When it is already on screen at
 * load, it turns true a short beat after the page has painted. Without
 * IntersectionObserver it is true at once.
 */
export function useInViewOnce(ref: RefObject<Element | null>, share = 0.4): boolean {
  const [seen, setSeen] = useState(false);

  useEffect(() => {
    const el = ref.current;
    if (seen || !el) return;
    if (!("IntersectionObserver" in window)) {
      setSeen(true);
      return;
    }
    let timer = 0;
    const io = new IntersectionObserver(
      (entries) => {
        const e = entries[entries.length - 1];
        if (!e || timer) return;
        const tall = Math.min(e.boundingClientRect.height, e.rootBounds?.height ?? window.innerHeight);
        if (!e.isIntersecting || e.intersectionRect.height < share * tall) return;
        io.disconnect();
        timer = window.setTimeout(() => setSeen(true), Math.max(BEAT, FIRST_BEAT - performance.now()));
      },
      { threshold: STEPS },
    );
    io.observe(el);
    return () => {
      io.disconnect();
      window.clearTimeout(timer);
    };
  }, [ref, share, seen]);

  return seen;
}
