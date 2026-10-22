'use client';

import Link from 'next/link';
import { Bot, Check, Copy } from 'lucide-react';
import { useState } from 'react';

const LLMS_URL = 'https://docs.syntropic137.com/llms.txt';

/** Top of the docs sidebar: the one URL to hand an agent, with a copy button and a link to every option. */
export function AgentDocsBanner() {
  const [copied, setCopied] = useState(false);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(LLMS_URL);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // Clipboard blocked: the URL is still on screen to select.
    }
  };

  return (
    <div className="syn-agent-docs">
      <span className="syn-agent-docs__title">
        <Bot className="syn-agent-docs__icon" aria-hidden="true" />
        Docs for agents
      </span>
      <p className="syn-agent-docs__body">Give your agent this URL and it can read every page.</p>
      <button type="button" className="syn-agent-docs__url" onClick={copy} aria-label={`Copy ${LLMS_URL}`}>
        <code>/llms.txt</code>
        {copied ? <Check aria-hidden="true" /> : <Copy aria-hidden="true" />}
      </button>
      <Link href="/llms" className="syn-agent-docs__more">
        System prompt and full docs
      </Link>
    </div>
  );
}
