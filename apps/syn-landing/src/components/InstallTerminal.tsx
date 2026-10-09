import { useState } from "react";
import { Clipboard, Check } from "lucide-react";

const COMMAND = "npx @syntropic137/setup";

export default function InstallTerminal({
  className,
  showHeader = true,
  style,
}: {
  className?: string;
  showHeader?: boolean;
  style?: React.CSSProperties;
}) {
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    await navigator.clipboard.writeText(COMMAND);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };

  return (
    <div className={`install-terminal glass ${className ?? ""}`} style={style}>
      {showHeader && (
        <div className="install-terminal-header">
          <span className="code-filename">terminal</span>
          <button
            className="install-copy"
            onClick={handleCopy}
            aria-label="Copy install command"
          >
            {copied ? <Check size={14} /> : <Clipboard size={14} />}
          </button>
        </div>
      )}
      <div className="terminal-line" onClick={handleCopy} role="button" tabIndex={0}>
        <code className="terminal-line-text">
          <span className="syn-punctuation">$ </span>
          <span className="syn-function">{COMMAND}</span>
        </code>
        {copied ? (
          <span className="terminal-copied-tooltip">Copied!</span>
        ) : (
          <Clipboard size={12} className="terminal-line-icon" />
        )}
      </div>
    </div>
  );
}
