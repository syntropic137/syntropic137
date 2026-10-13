/**
 * Dark Shiki theme for the docs, matching the landing page's code windows
 * (v4 Landing board): primary text on the panel, muted keys, harness and
 * status colours for the few highlights. Colours are CSS variables
 * (--syn-code-*, defined in app/global.css from Skyline tokens), so the theme
 * holds no colour values of its own. Light mode keeps github-light.
 */
import type { ThemeRegistrationRaw } from 'shiki';

const v = (name: string) => `var(--syn-code-${name})`;

export const skylineCodeTheme: ThemeRegistrationRaw = {
  name: 'syn-skyline',
  type: 'dark',
  colors: {
    'editor.background': v('bg'),
    'editor.foreground': v('fg'),
  },
  settings: [
    { settings: { foreground: v('fg'), background: v('bg') } },
    {
      scope: ['comment', 'punctuation.definition.comment', 'string.comment'],
      settings: { foreground: v('comment'), fontStyle: 'italic' },
    },
    {
      scope: [
        'entity.name.tag.yaml',
        'support.type.property-name',
        'meta.object-literal.key',
        'variable.other.property',
        'variable.other.object.property',
        'entity.other.attribute-name',
        'variable.other.env',
        'variable.other.assignment.shell',
        'meta.mapping.key',
      ],
      settings: { foreground: v('key') },
    },
    {
      scope: [
        'keyword',
        'storage',
        'storage.type',
        'storage.modifier',
        'keyword.control',
        'keyword.operator.new',
        'keyword.operator.expression',
        'variable.language',
      ],
      settings: { foreground: v('keyword') },
    },
    {
      scope: ['string', 'string.quoted', 'string.unquoted', 'markup.inline.raw', 'string.template'],
      settings: { foreground: v('string') },
    },
    {
      scope: ['constant.numeric', 'constant.language', 'constant.character', 'constant.other', 'support.constant'],
      settings: { foreground: v('constant') },
    },
    {
      scope: [
        'entity.name.function',
        'support.function',
        'support.function.builtin',
        'entity.name.command',
        'meta.function-call',
        'entity.name.type',
        'support.type',
        'support.class',
        'entity.name.class',
        'entity.name.tag',
      ],
      settings: { foreground: v('function') },
    },
    {
      scope: ['punctuation', 'meta.brace', 'keyword.operator'],
      settings: { foreground: v('punctuation') },
    },
    { scope: ['markup.heading', 'markup.bold'], settings: { foreground: v('fg'), fontStyle: 'bold' } },
    { scope: ['markup.inserted'], settings: { foreground: v('inserted') } },
    { scope: ['markup.deleted'], settings: { foreground: v('deleted') } },
    { scope: ['invalid'], settings: { foreground: v('deleted') } },
  ],
};

export const codeThemes = {
  light: 'github-light',
  dark: skylineCodeTheme,
};
