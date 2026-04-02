import { generateFiles } from 'fumadocs-openapi';
import { createOpenAPI } from 'fumadocs-openapi/server';

const openapi = createOpenAPI({
  input: ['./openapi.json'],
});

async function main() {
  await generateFiles({
    input: openapi,
    output: './content/docs/api',
    per: 'tag',
    frontmatter: () => ({ full: false }),
  });

  console.log('Generated API reference docs from OpenAPI spec');
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
