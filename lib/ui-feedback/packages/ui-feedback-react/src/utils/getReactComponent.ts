/**
 * Utilities for detecting React component names from DOM elements
 */

interface FiberNode {
  type: { name?: string; displayName?: string } | string | null;
  return: FiberNode | null;
}

/**
 * Try to get the React component name for an element.
 *
 * This works by accessing React's internal fiber data structure.
 * It's not guaranteed to work in all cases (minified production builds,
 * future React versions, etc.) but provides useful debug info when available.
 */
export function getReactComponentName(element: Element): string | null {
  // Try to find React fiber
  const fiberKey = Object.keys(element).find(
    (key) =>
      key.startsWith('__reactFiber$') ||
      key.startsWith('__reactInternalInstance$')
  );

  if (!fiberKey) {
    return null;
  }

  const fiber = (element as unknown as Record<string, FiberNode>)[fiberKey];
  if (!fiber) {
    return null;
  }

  // Walk up the fiber tree to find a function component
  let current: FiberNode | null = fiber;
  const maxDepth = 20; // Prevent infinite loops
  let depth = 0;

  while (current && depth < maxDepth) {
    const type = current.type;

    // Check if this is a function/class component
    if (typeof type === 'function' || (typeof type === 'object' && type !== null)) {
      const componentType = type as { name?: string; displayName?: string };
      const name = componentType.displayName || componentType.name;

      // Filter out internal React components and common wrappers
      if (
        name &&
        !name.startsWith('_') &&
        !['Fragment', 'Suspense', 'StrictMode', 'Provider', 'Consumer'].includes(name)
      ) {
        return name;
      }
    }

    current = current.return;
    depth++;
  }

  return null;
}

/**
 * Get component name with fallback to data attributes
 */
export function getComponentInfo(element: Element): string | null {
  // Try React fiber first
  const reactName = getReactComponentName(element);
  if (reactName) {
    return reactName;
  }

  // Fallback to data attributes
  let current: Element | null = element;
  while (current && current !== document.body) {
    const dataComponent = current.getAttribute('data-component');
    if (dataComponent) {
      return dataComponent;
    }

    const dataTestId = current.getAttribute('data-testid');
    if (dataTestId) {
      // Convert test-id like "submit-button" to "SubmitButton"
      return dataTestId
        .split(/[-_]/)
        .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
        .join('');
    }

    current = current.parentElement;
  }

  return null;
}
