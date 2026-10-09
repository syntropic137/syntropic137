import type { ReactNode } from "react";
import "./CodeWindow.css";

interface CodeWindowProps {
  /** Title bar text (a file path, a command, a host). Without it there is no title bar: a plain panel. */
  title?: string;
  children: ReactNode;
  className?: string;
  /** Padding of the body: "code" for a <pre>, "panel" (18px), "roomy" (28px on wide screens), "none". */
  pad?: "code" | "panel" | "roomy" | "none";
  /** Accent light in the top right corner (the observability panel). */
  glow?: boolean;
}

/**
 * Window chrome of the v4 boards: rounded panel with the panel gradient and,
 * with a title, a bar of three dots and a mono label. Used for code files,
 * command output and dashboard previews.
 */
export default function CodeWindow({ title, children, className, pad = "panel", glow = false }: CodeWindowProps) {
  return (
    <div className={`code-window${glow ? " code-window--glow" : ""}${className ? ` ${className}` : ""}`}>
      {title !== undefined && (
        <div className="code-window__bar">
          <span className="code-window__dots" aria-hidden="true">
            <span />
            <span />
            <span />
          </span>
          <span className="code-window__title">{title}</span>
        </div>
      )}
      <div className="code-window__body" data-pad={pad}>
        {children}
      </div>
    </div>
  );
}

/** A small labelled tile inside or beside a window ("From the CLI", "Phases"). */
export function Tile({ label, children, className }: { label: string; children: ReactNode; className?: string }) {
  return (
    <div className={`code-tile${className ? ` ${className}` : ""}`}>
      <span className="code-tile__label">{label}</span>
      {children}
    </div>
  );
}

/** The live dot with its halo, before a mono status line. */
export function LiveDot() {
  return <span className="live-dot" aria-hidden="true" />;
}
