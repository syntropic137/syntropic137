export function stripFrontmatter(content: string): string {
  const match = content.match(/^---\n[\s\S]*?\n---\n?/);
  return match ? content.slice(match[0].length).trim() : content.trim();
}

export function stripJSX(content: string): string {
  let result = content;
  result = result.replace(/\{\/\*[\s\S]*?\*\/\}/g, '');
  result = result.replace(/<[A-Z][A-Za-z]*(?:\s[^]*?)?\/>/g, '');
  result = result.replace(/<([A-Z][A-Za-z]*)(?:\s[^]*?)?>[^]*?<\/\1>/g, '');
  result = result.replace(/\n{3,}/g, '\n\n');
  return result.trim();
}

export function parseFrontmatter(content: string): { title?: string; description?: string } {
  const match = content.match(/^---\n([\s\S]*?)\n---/);
  if (!match) return {};
  const fm: Record<string, string> = {};
  for (const line of match[1].split('\n')) {
    if (/^\w/.test(line)) {
      const [key, ...rest] = line.split(':');
      if (key && rest.length) fm[key.trim()] = rest.join(':').trim();
    }
  }
  return { title: fm.title, description: fm.description };
}
