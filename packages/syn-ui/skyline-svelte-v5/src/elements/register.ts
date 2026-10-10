/**
 * Shared by the element entries. A wrapper compiled with the customElement
 * option registers its tag when its module first runs (Svelte's `tag`
 * option) and exposes the class as `.element`; ES modules run once, so a
 * page that imports one element and then all of them defines each tag once.
 */
export function elementClass(component: unknown): CustomElementConstructor | undefined {
  return (component as { element?: CustomElementConstructor }).element
}
