import { useEffect, useRef, useState } from 'react';
import type { Components } from 'react-markdown';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import mermaid from 'mermaid';

interface MarkdownViewerProps {
    content: string;
    className?: string;
}

// Initialize mermaid with dark theme
mermaid.initialize({
    startOnLoad: false,
    theme: 'dark',
    securityLevel: 'loose',
    fontFamily: 'JetBrains Mono, monospace',
});

// Mermaid diagram component
function MermaidDiagram({ code }: { code: string }) {
    const containerRef = useRef<HTMLDivElement>(null);
    const [svg, setSvg] = useState<string>('');
    const [error, setError] = useState<string | null>(null);

    useEffect(() => {
        const renderDiagram = async () => {
            if (!containerRef.current) return;

            try {
                const id = `mermaid-${Math.random().toString(36).substr(2, 9)}`;
                const { svg } = await mermaid.render(id, code);
                setSvg(svg);
                setError(null);
            } catch (err) {
                setError(err instanceof Error ? err.message : 'Failed to render diagram');
                setSvg('');
            }
        };

        renderDiagram();
    }, [code]);

    if (error) {
        return (
            <div className="bg-red-900/20 border border-red-500/30 rounded-lg p-4 my-4">
                <p className="text-red-400 text-sm font-mono">Mermaid Error: {error}</p>
                <pre className="text-zinc-400 text-xs mt-2 overflow-x-auto">{code}</pre>
            </div>
        );
    }

    return (
        <div
            ref={containerRef}
            className="my-4 flex justify-center bg-zinc-900/50 rounded-lg p-4 overflow-x-auto"
            dangerouslySetInnerHTML={{ __html: svg }}
        />
    );
}

// Code block component with Mermaid support
function CodeBlock({
    className,
    children
}: {
    className?: string;
    children?: React.ReactNode;
}) {
    const match = /language-(\w+)/.exec(className || '');
    const language = match ? match[1] : '';
    const code = String(children).replace(/\n$/, '');

    // Render Mermaid diagrams
    if (language === 'mermaid') {
        return <MermaidDiagram code={code} />;
    }

    // Regular code block
    return (
        <div className="relative group my-4">
            {language && (
                <span className="absolute top-2 right-2 text-xs text-zinc-500 font-mono">
                    {language}
                </span>
            )}
            <pre className="bg-zinc-900 border border-zinc-700 rounded-lg p-4 overflow-x-auto">
                <code className={`text-sm font-mono text-zinc-300 ${className || ''}`}>
                    {code}
                </code>
            </pre>
        </div>
    );
}

/**
 * ReactMarkdown component overrides for dark-themed rendering.
 * Defined at module level to avoid re-creation on each render.
 */
const markdownComponents: Components = {
    // Headings
    h1: ({ children }) => (
        <h1 className="text-2xl font-bold text-white border-b border-zinc-700 pb-2 mb-4 mt-6">
            {children}
        </h1>
    ),
    h2: ({ children }) => (
        <h2 className="text-xl font-semibold text-zinc-100 border-b border-zinc-800 pb-2 mb-3 mt-5">
            {children}
        </h2>
    ),
    h3: ({ children }) => (
        <h3 className="text-lg font-semibold text-zinc-200 mb-2 mt-4">
            {children}
        </h3>
    ),
    h4: ({ children }) => (
        <h4 className="text-base font-semibold text-zinc-300 mb-2 mt-3">
            {children}
        </h4>
    ),

    // Paragraphs and text
    p: ({ children }) => (
        <p className="text-zinc-300 leading-relaxed mb-4">{children}</p>
    ),
    strong: ({ children }) => (
        <strong className="text-white font-semibold">{children}</strong>
    ),
    em: ({ children }) => (
        <em className="text-zinc-200 italic">{children}</em>
    ),

    // Links
    a: ({ href, children }) => (
        <a
            href={href}
            target="_blank"
            rel="noopener noreferrer"
            className="text-cyan-400 hover:text-cyan-300 underline underline-offset-2"
        >
            {children}
        </a>
    ),

    // Lists
    ul: ({ children }) => (
        <ul className="list-disc list-inside space-y-1 mb-4 text-zinc-300 ml-4">
            {children}
        </ul>
    ),
    ol: ({ children }) => (
        <ol className="list-decimal list-inside space-y-1 mb-4 text-zinc-300 ml-4">
            {children}
        </ol>
    ),
    li: ({ children }) => (
        <li className="text-zinc-300">{children}</li>
    ),

    // Code
    code: ({ className, children }) => {
        const isInline = !className;
        if (isInline) {
            return (
                <code className="bg-zinc-800 text-cyan-300 px-1.5 py-0.5 rounded text-sm font-mono">
                    {children}
                </code>
            );
        }
        return <CodeBlock className={className}>{children}</CodeBlock>;
    },
    pre: ({ children }) => <>{children}</>,

    // Blockquotes
    blockquote: ({ children }) => (
        <blockquote className="border-l-4 border-cyan-500/50 pl-4 my-4 text-zinc-400 italic">
            {children}
        </blockquote>
    ),

    // Tables (GFM)
    table: ({ children }) => (
        <div className="overflow-x-auto my-4">
            <table className="min-w-full border border-zinc-700 rounded-lg overflow-hidden">
                {children}
            </table>
        </div>
    ),
    thead: ({ children }) => (
        <thead className="bg-zinc-800">{children}</thead>
    ),
    tbody: ({ children }) => (
        <tbody className="divide-y divide-zinc-700">{children}</tbody>
    ),
    tr: ({ children }) => (
        <tr className="hover:bg-zinc-800/50">{children}</tr>
    ),
    th: ({ children }) => (
        <th className="px-4 py-2 text-left text-sm font-semibold text-zinc-200">
            {children}
        </th>
    ),
    td: ({ children }) => (
        <td className="px-4 py-2 text-sm text-zinc-300">{children}</td>
    ),

    // Horizontal rule
    hr: () => <hr className="border-zinc-700 my-6" />,

    // Task lists (GFM)
    input: ({ checked }) => (
        <input
            type="checkbox"
            checked={checked}
            readOnly
            className="mr-2 accent-cyan-500"
        />
    ),
};

export function MarkdownViewer({ content, className = '' }: MarkdownViewerProps) {
    return (
        <div className={`markdown-viewer prose prose-invert max-w-none ${className}`}>
            <ReactMarkdown
                remarkPlugins={[remarkGfm]}
                components={markdownComponents}
            >
                {content}
            </ReactMarkdown>
        </div>
    );
}

export default MarkdownViewer;
