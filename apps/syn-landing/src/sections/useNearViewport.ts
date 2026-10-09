import { useEffect, useState, type RefObject } from "react";

/**
 * True once `ref` comes within `margin` of the viewport (and stays true).
 * Below-the-fold sections use it to load their <sky-*> element late, so
 * the first paint never waits for it.
 */
export function useNearViewport(ref: RefObject<Element | null>, margin = "600px"): boolean {
  const [near, setNear] = useState(false);
  useEffect(() => {
    const el = ref.current;
    if (!el || near) return;
    if (!("IntersectionObserver" in window)) {
      setNear(true);
      return;
    }
    const io = new IntersectionObserver(
      (entries) => {
        if (entries.some((e) => e.isIntersecting)) {
          setNear(true);
          io.disconnect();
        }
      },
      { rootMargin: `${margin} 0px` },
    );
    io.observe(el);
    return () => io.disconnect();
  }, [ref, margin, near]);
  return near;
}
