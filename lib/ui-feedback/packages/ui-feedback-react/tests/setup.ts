// jsdom gaps that every browser the widget runs in fills.
if (typeof globalThis.CSS === 'undefined') {
  Object.defineProperty(globalThis, 'CSS', {
    value: { escape: (s: string) => s.replace(/[^\w-]/g, (c) => `\\${c}`) },
  });
}
// No layout in jsdom; the touch pre-highlight only needs this to exist.
document.elementsFromPoint = () => [];
