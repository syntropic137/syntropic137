import packageJson from '../package.json';

const LAST_UPDATED = 'March 2026';

export function DocsFooter() {
  return (
    <div className="mt-12 border-t border-fd-border pt-4 pb-2 not-prose">
      <p className="text-xs text-fd-muted-foreground">
        Syntropic137 Docs v{packageJson.version} &middot; Last updated{' '}
        {LAST_UPDATED}
      </p>
    </div>
  );
}
