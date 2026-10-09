import { useState } from "react";
import { Clipboard, Check } from "lucide-react";
import FadeIn from "./FadeIn";

const installCommand = "npx @syntropic137/setup";

export default function Install() {
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    await navigator.clipboard.writeText(installCommand);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <section id="install" className="section">
      <div className="container install-container">
        <FadeIn>
          <h2 className="section-heading">
            Up and <span className="accent">Running</span> in Minutes
          </h2>
          <p className="section-subtitle">
            Only prerequisite: Docker. One command handles everything else.
          </p>

          <div className="get-started-install glass">
            <div className="get-started-install-header">
              <span className="code-filename">quick start</span>
              <button
                className="install-copy"
                onClick={handleCopy}
                aria-label="Copy install command"
              >
                {copied ? <Check size={14} /> : <Clipboard size={14} />}
              </button>
            </div>
            <pre className="get-started-code">
              <code>
                <span className="syn-punctuation">$ </span>
                <span className="syn-function">{installCommand}</span>
              </code>
            </pre>
          </div>
        </FadeIn>
      </div>
    </section>
  );
}
