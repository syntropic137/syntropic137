/**
 * Utilities for generating CSS selectors and XPath for DOM elements
 */

/**
 * Generate a unique CSS selector for an element
 */
export function getCssSelector(element: Element): string {
  const path: string[] = [];
  let current: Element | null = element;

  while (current && current !== document.body && current !== document.documentElement) {
    let selector = current.tagName.toLowerCase();

    // Add ID if present and unique
    if (current.id) {
      selector = `#${CSS.escape(current.id)}`;
      path.unshift(selector);
      break; // ID should be unique, no need to go further
    }

    // Add classes if present
    if (current.classList.length > 0) {
      const classes = Array.from(current.classList)
        .filter((c) => !c.startsWith('ui-feedback-')) // Exclude our own classes
        .map((c) => `.${CSS.escape(c)}`)
        .join('');
      if (classes) {
        selector += classes;
      }
    }

    // Add nth-child if needed for uniqueness
    const parent = current.parentElement;
    if (parent) {
      const siblings = Array.from(parent.children).filter(
        (child) => child.tagName === current!.tagName
      );
      if (siblings.length > 1) {
        const index = siblings.indexOf(current) + 1;
        selector += `:nth-child(${index})`;
      }
    }

    path.unshift(selector);
    current = current.parentElement;
  }

  return path.join(' > ');
}

/**
 * Generate an XPath for an element
 */
export function getXPath(element: Element): string {
  const parts: string[] = [];
  let current: Element | null = element;

  while (current && current !== document.body && current !== document.documentElement) {
    let part = current.tagName.toLowerCase();

    // Add ID if present
    if (current.id) {
      part = `//*[@id="${current.id}"]`;
      parts.unshift(part);
      break;
    }

    // Calculate position among siblings with same tag
    const parent = current.parentElement;
    if (parent) {
      const siblings = Array.from(parent.children).filter(
        (child) => child.tagName === current!.tagName
      );
      if (siblings.length > 1) {
        const index = siblings.indexOf(current) + 1;
        part += `[${index}]`;
      }
    }

    parts.unshift(part);
    current = current.parentElement;
  }

  // If first part is an ID selector, return as-is
  if (parts[0]?.startsWith('//*[@id=')) {
    return parts.join('/');
  }

  return '//' + parts.join('/');
}

/**
 * Try to find a data-testid or data-component attribute
 */
export function getDataAttribute(element: Element): string | null {
  let current: Element | null = element;

  while (current && current !== document.body) {
    // Check for common test/component identifier attributes
    const testId = current.getAttribute('data-testid');
    if (testId) return `[data-testid="${testId}"]`;

    const componentId = current.getAttribute('data-component');
    if (componentId) return `[data-component="${componentId}"]`;

    const cy = current.getAttribute('data-cy');
    if (cy) return `[data-cy="${cy}"]`;

    current = current.parentElement;
  }

  return null;
}
