'use client';

import { Callout as FDCallout } from 'fumadocs-ui/components/callout';
import type { ComponentProps } from 'react';

/**
 * Enhanced Callout — wraps Fumadocs' Callout and adds the `syn-callout` class
 * so global.css can apply tinted backgrounds and thicker accent bars.
 */
export function Callout({ className, ...props }: ComponentProps<typeof FDCallout>) {
  return (
    <FDCallout
      {...props}
      className={`syn-callout ${className ?? ''}`}
    />
  );
}
