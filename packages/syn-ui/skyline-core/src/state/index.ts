// Small framework-free state machines (reducers). Phase agents add:
// day stepper, selection, filters. See CONVENTIONS.md "skyline-core".
export { run } from './machine'
export type { Reducer } from './machine'
export { copyFeedback, COPY_FEEDBACK_MS } from './copyFeedback'
export type { CopyState, CopyEvent } from './copyFeedback'
