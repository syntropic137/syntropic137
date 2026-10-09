import { useEffect, useLayoutEffect, useReducer, useRef, useState, type CSSProperties, type RefObject } from "react";
import { copyFeedback, COPY_FEEDBACK_MS, type CopyState } from "@syn137/skyline-core/state";
import { HERO, INSTALL_COMMAND } from "../data/copy";
import "./InstallTerminal.css";

interface InstallTerminalProps {
  className?: string;
  style?: CSSProperties;
  /** Type the command out once it is on screen (hero). The caret blinks only while visible, for about 20s. */
  typing?: boolean;
}

const onScreen = (el: Element) => {
  const r = el.getBoundingClientRect();
  return r.bottom > 0 && r.top < window.innerHeight;
};

/** started: the typing has begun (sticky); visible: the box is on screen now. */
function useTyping(ref: RefObject<HTMLDivElement | null>, enabled: boolean) {
  const [state, setState] = useState({ started: false, visible: false });

  // Start before first paint when already on screen, so the full command never flashes first.
  useLayoutEffect(() => {
    if (enabled && ref.current && onScreen(ref.current)) setState({ started: true, visible: true });
  }, [enabled, ref]);

  useEffect(() => {
    const el = ref.current;
    if (!enabled || !el || !("IntersectionObserver" in window)) return;
    const io = new IntersectionObserver(([e]) => {
      const visible = e?.isIntersecting ?? false;
      setState((s) => ({ started: s.started || visible, visible }));
    });
    io.observe(el);
    return () => io.disconnect();
  }, [enabled, ref]);

  return state;
}

/** Copy with skyline-core's copyFeedback states; copied and failed reset after COPY_FEEDBACK_MS. */
function useCopy(text: string) {
  const [state, send] = useReducer(copyFeedback, "idle");
  useEffect(() => {
    if (state !== "copied" && state !== "failed") return;
    const id = window.setTimeout(() => send({ type: "reset" }), COPY_FEEDBACK_MS);
    return () => window.clearTimeout(id);
  }, [state]);
  const copy = () => {
    send({ type: "copy" });
    Promise.resolve()
      .then(() => navigator.clipboard.writeText(text))
      .then(
        () => send({ type: "success" }),
        () => send({ type: "error" }),
      );
  };
  return { state, copy };
}

const COPY_LABEL: Record<CopyState, string> = { idle: HERO.copyLabel, copying: HERO.copyLabel, copied: HERO.copiedLabel, failed: HERO.copyFailedLabel };
const COPY_ANNOUNCE: Record<CopyState, string> = { idle: "", copying: "", copied: HERO.copiedAnnounce, failed: HERO.copyFailedAnnounce };

function CopyIcon({ done }: { done: boolean }) {
  return (
    <svg width="15" height="15" viewBox="0 0 16 16" aria-hidden="true" focusable="false">
      {done ? (
        <path d="M3.5 8.5l3 3 6-7" />
      ) : (
        <>
          <rect x="5.5" y="5.5" width="8" height="8" rx="1.5" />
          <path d="M10.5 5.5V3.5a1 1 0 0 0-1-1h-6a1 1 0 0 0-1 1v6a1 1 0 0 0 1 1h2" />
        </>
      )}
    </svg>
  );
}

const CHARS = INSTALL_COMMAND.length;
const TYPE_STYLE = { width: `${CHARS}ch`, animationTimingFunction: `steps(${CHARS})` } as CSSProperties;

/** The command, revealed with motion.css sky-type and a blinking caret once `started`. */
function Command({ typing, started }: { typing: boolean; started: boolean }) {
  if (!typing) return <span className="install-box__cmd">{INSTALL_COMMAND}</span>;
  const motion = started ? " sky-type" : "";
  return (
    <>
      <span className={`install-box__cmd${motion}`} style={TYPE_STYLE}>
        {INSTALL_COMMAND}
      </span>
      <span className={started ? "install-box__caret sky-blink" : "install-box__caret"} aria-hidden="true" />
    </>
  );
}

/**
 * The install box of the v4 boards: prompt, `npx @syntropic137/setup init`
 * and a Copy button. The full command is always in the DOM (and is the
 * static end state); typing only reveals it. Used by the hero, the closing
 * call to action and the links page. The button keeps its name ("Copy
 * install command"); the result is announced in a polite status message.
 */
export default function InstallTerminal({ className, style, typing = false }: InstallTerminalProps) {
  const ref = useRef<HTMLDivElement>(null);
  const { started, visible } = useTyping(ref, typing);
  const { state, copy } = useCopy(INSTALL_COMMAND);
  const classes = className ? `install-box ${className}` : "install-box";

  return (
    <div ref={ref} className={classes} style={style} data-state={state} data-paused={typing && !visible ? "" : undefined}>
      <span className="install-box__prompt" aria-hidden="true">
        ❯
      </span>
      <code className="install-box__code">
        <Command typing={typing} started={started} />
      </code>
      <button type="button" className="install-box__copy" onClick={copy} aria-label={HERO.copyAria}>
        <CopyIcon done={state === "copied"} />
        <span aria-hidden="true">{COPY_LABEL[state]}</span>
      </button>
      <span className="sr-only" role="status">
        {COPY_ANNOUNCE[state]}
      </span>
    </div>
  );
}
