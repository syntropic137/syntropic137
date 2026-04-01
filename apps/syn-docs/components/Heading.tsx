'use client';

import { cn } from 'fumadocs-ui/utils/cn';
import { Link } from 'lucide-react';
import { useState, type ComponentPropsWithoutRef } from 'react';

function CopyHeading({
  as,
  className,
  ...props
}: ComponentPropsWithoutRef<'h1'> & { as?: 'h1' | 'h2' | 'h3' | 'h4' | 'h5' | 'h6' }) {
  const As = as ?? 'h1';
  const [copied, setCopied] = useState(false);

  if (!props.id) return <As className={className} {...props} />;

  const handleCopyLink = (e: React.MouseEvent) => {
    e.preventDefault();
    const url = `${window.location.origin}${window.location.pathname}#${props.id}`;
    navigator.clipboard.writeText(url).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  };

  return (
    <As
      className={cn('group flex scroll-m-28 flex-row items-center gap-2', className)}
      {...props}
    >
      <a data-card="" href={`#${props.id}`} className="peer">
        {props.children}
      </a>
      <button
        onClick={handleCopyLink}
        className={cn(
          'size-3.5 shrink-0 transition-opacity group-hover:opacity-100 cursor-pointer',
          copied ? 'opacity-100 text-teal-400' : 'opacity-0 text-fd-muted-foreground'
        )}
        title={copied ? 'Copied!' : 'Copy link'}
        aria-label="Copy link to section"
      >
        <Link className="size-3.5" />
      </button>
    </As>
  );
}

export const heading = {
  h1: (props: ComponentPropsWithoutRef<'h1'>) => <CopyHeading as="h1" {...props} />,
  h2: (props: ComponentPropsWithoutRef<'h2'>) => <CopyHeading as="h2" {...props} />,
  h3: (props: ComponentPropsWithoutRef<'h3'>) => <CopyHeading as="h3" {...props} />,
  h4: (props: ComponentPropsWithoutRef<'h4'>) => <CopyHeading as="h4" {...props} />,
  h5: (props: ComponentPropsWithoutRef<'h5'>) => <CopyHeading as="h5" {...props} />,
  h6: (props: ComponentPropsWithoutRef<'h6'>) => <CopyHeading as="h6" {...props} />,
};
