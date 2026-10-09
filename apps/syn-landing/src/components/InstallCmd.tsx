import { useState } from "react";
import { Clipboard, Check } from "lucide-react";

export default function InstallCmd() {
  const [copied, setCopied] = useState(false);
  const command = "npx @syntropic137/setup";

  const handleCopy = async () => {
    await navigator.clipboard.writeText(command);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <code className="install-cmd">
      <span className="install-prefix">$ </span>
      <span className="install-text">{command}</span>
      <button className="install-copy" onClick={handleCopy} aria-label="Copy command">
        {copied ? <Check size={14} /> : <Clipboard size={14} />}
      </button>
    </code>
  );
}
