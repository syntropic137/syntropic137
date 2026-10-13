import { useEffect, useState, type RefObject } from "react";

/**
 * Loads a <sky-*> element module once and reports when its tag is defined.
 *
 * Elements that take arrays or objects (the city, lanes, ticker, usage
 * band) render only once defined, so React 19 sets those props as
 * properties on the upgraded element; until then the caller shows a static
 * fallback. `when: "idle"` loads after first paint (above the fold);
 * `when: "near"` loads as `ref` comes within 600px of the viewport.
 */
const modules = new Map<string, Promise<unknown>>();

export function loadElement(tag: string, load: () => Promise<unknown>): Promise<unknown> {
  let p = modules.get(tag);
  if (!p) {
    p = load().catch(() => undefined);
    modules.set(tag, p);
  }
  return p;
}

const defined = (tag: string) => typeof customElements !== "undefined" && customElements.get(tag) !== undefined;

export function useElement(
  tag: string,
  load: () => Promise<unknown>,
  when: "idle" | "near",
  ref?: RefObject<Element | null>,
): boolean {
  const [ready, setReady] = useState(() => defined(tag));

  useEffect(() => {
    if (ready) return;
    let live = true;
    const start = () => {
      void loadElement(tag, load);
      void customElements.whenDefined(tag).then(() => live && setReady(true));
    };
    let cancel = () => {};
    if (when === "near" && ref?.current && "IntersectionObserver" in window) {
      const io = new IntersectionObserver(
        (entries) => {
          if (entries.some((e) => e.isIntersecting)) {
            io.disconnect();
            start();
          }
        },
        { rootMargin: "600px 0px" },
      );
      io.observe(ref.current);
      cancel = () => io.disconnect();
    } else if ("requestIdleCallback" in window) {
      const id = window.requestIdleCallback(start, { timeout: 1500 });
      cancel = () => window.cancelIdleCallback(id);
    } else {
      const id = globalThis.setTimeout(start, 1);
      cancel = () => globalThis.clearTimeout(id);
    }
    return () => {
      live = false;
      cancel();
    };
  }, [tag, when, ready]);

  return ready;
}
