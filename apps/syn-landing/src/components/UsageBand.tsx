import { useRef } from "react";
import type { TokenBreakdown } from "@syn137/skyline-core/format";
import { useElement } from "./useElement";
import "./UsageBand.css";

const loadBand = () => import("@syn137/skyline-svelte-v5/elements/usage-band");

/** Series in the band's order, with the Skyline data tokens skyline-core's TOKEN_SERIES uses. */
const SERIES = [
  { key: "cacheRead", label: "Cache read", token: "var(--sky-color-data-1)" },
  { key: "cacheWrite", label: "Cache write", token: "var(--sky-color-data-2)" },
  { key: "output", label: "Output", token: "var(--sky-color-data-3)" },
  { key: "input", label: "Input", token: "var(--sky-color-data-4)" },
] as const;

interface UsageBandProps {
  tokens: TokenBreakdown;
  /** Swatches and names under the bar ("compact"), or none. */
  legend?: "compact" | "none";
  /** Bar height: "sm" 14px ("What is" card), "md" 22px (observability). */
  size?: "sm" | "md";
}

/**
 * <sky-usage-band> (flat, the landing's bar) loaded as it nears the
 * viewport, with a static flat bar of the same shares until it is defined.
 */
export default function UsageBand({ tokens, legend = "none", size = "sm" }: UsageBandProps) {
  const ref = useRef<HTMLDivElement>(null);
  const ready = useElement("sky-usage-band", loadBand, "near", ref);
  return (
    <div ref={ref} className="usage-band" data-size={size}>
      {ready ? (
        <sky-usage-band shape="flat" legend={legend} tokens={tokens} />
      ) : (
        <div className="usage-band__fallback">
          <div className="usage-band__bar">
            {SERIES.map((s) => (
              <span key={s.key} style={{ flexGrow: tokens[s.key], background: s.token }} />
            ))}
          </div>
          {legend === "compact" && (
            <div className="usage-band__legend">
              {SERIES.map((s) => (
                <span key={s.key}>
                  <span className="usage-band__swatch" style={{ background: s.token }} />
                  {s.label}
                </span>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
