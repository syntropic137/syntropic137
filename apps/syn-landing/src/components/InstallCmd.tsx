import { useEffect, useReducer, useRef } from "react";
import { copyFeedback, COPY_FEEDBACK_MS } from "@syn137/skyline-core/state";
import { useNearViewport } from "../sections/useNearViewport";
import { INSTALL_COMMAND } from "../data/copy";
import "./InstallCmd.css";

const CopyIcon = () => (
  <svg width="15" height="15" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinejoin="round" aria-hidden="true">
    <rect x="5.5" y="5.5" width="8" height="8" rx="1.5" />
    <path d="M10.5 5.5V4a1.5 1.5 0 0 0-1.5-1.5H4A1.5 1.5 0 0 0 2.5 4v5A1.5 1.5 0 0 0 4 10.5h1.5" />
  </svg>
);

const CheckIcon = () => (
  <svg width="15" height="15" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M3.5 8.5l3 3 6-7" />
  </svg>
);

const LABEL = { idle: "Copy", copying: "Copy", copied: "Copied", failed: "Copy failed" } as const;
const ANNOUNCE = { idle: "", copying: "", copied: "Install command copied to the clipboard", failed: "Could not copy. Select the command and copy it." } as const;

/**
 * The copy-command box (closing call to action): a prompt, the install
 * command typing out once it scrolls into view, and a Copy button. The
 * button's label changes to "Copied" and a polite live region announces it;
 * skyline-core's copyFeedback reducer runs the states.
 */
export default function InstallCmd({ command = INSTALL_COMMAND }: { command?: string }) {
  const [state, send] = useReducer(copyFeedback, "idle");
  const box = useRef<HTMLDivElement>(null);
  const seen = useNearViewport(box, "0px");

  useEffect(() => {
    if (state !== "copied" && state !== "failed") return;
    const t = window.setTimeout(() => send({ type: "reset" }), COPY_FEEDBACK_MS);
    return () => window.clearTimeout(t);
  }, [state]);

  const copy = async () => {
    send({ type: "copy" });
    try {
      await navigator.clipboard.writeText(command);
      send({ type: "success" });
    } catch {
      send({ type: "error" });
    }
  };

  return (
    <div ref={box} className="install-box" data-state={state}>
      <span className="install-box__prompt" aria-hidden="true">
        ❯
      </span>
      <code className="install-box__cmd">
        <span className={seen ? "install-box__text sky-type" : "install-box__text"} style={{ width: `${command.length}ch` }}>
          {command}
        </span>
        <span className={seen ? "install-box__caret sky-blink" : "install-box__caret"} aria-hidden="true" />
      </code>
      <button type="button" className="install-box__copy" onClick={copy} aria-label="Copy install command">
        {state === "copied" ? <CheckIcon /> : <CopyIcon />}
        <span aria-hidden="true">{LABEL[state]}</span>
      </button>
      <span className="install-box__status" role="status" aria-live="polite">
        {ANNOUNCE[state]}
      </span>
    </div>
  );
}
