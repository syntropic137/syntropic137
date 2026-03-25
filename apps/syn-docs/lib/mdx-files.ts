import fs from 'node:fs';
import path from 'node:path';

interface MdxFile {
  filepath: string;
  content: string;
}

function walkDirectory(dir: string, results: MdxFile[]): void {
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      walkDirectory(full, results);
    } else if (entry.name.endsWith('.mdx')) {
      results.push({ filepath: full, content: fs.readFileSync(full, 'utf-8') });
    }
  }
}

export function collectMdxFiles(dir: string): MdxFile[] {
  const results: MdxFile[] = [];
  walkDirectory(dir, results);
  return results;
}
