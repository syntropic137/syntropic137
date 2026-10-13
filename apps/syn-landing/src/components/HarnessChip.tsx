import { useEffect } from "react";
import { HARNESSES } from "../data/harnesses";
import { loadElement } from "./useElement";
import "./HarnessChip.css";

const loadChip = () => import("@syn137/skyline-svelte-v5/elements/harness-chip");

/**
 * <sky-harness-chip> with a light-DOM fallback in the same shape: a dot in
 * the harness colour (src/data/harnesses.ts) and the label. Strings only,
 * so the element can be in the DOM before its module loads.
 */
export default function HarnessChip({ provider, label }: { provider: string; label: string }) {
  useEffect(() => {
    const go = () => void loadElement("sky-harness-chip", loadChip);
    if ("requestIdleCallback" in window) window.requestIdleCallback(go, { timeout: 2000 });
    else setTimeout(go, 1);
  }, []);
  const harness = HARNESSES.find((h) => h.id === provider);
  return (
    <sky-harness-chip className="harness-chip" provider={provider} label={label}>
      <span className="harness-chip__fallback">
        <span className="harness-chip__dot" style={{ background: harness?.color }} aria-hidden="true" />
        {label}
      </span>
    </sky-harness-chip>
  );
}
