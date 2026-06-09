import '@testing-library/jest-dom/vitest'
import { afterEach, beforeEach, vi } from 'vitest'

// Expose vitest's `vi` object as `jest` so that @testing-library/dom's
// jestFakeTimersAreEnabled() can detect vitest fake timers and make
// waitFor() advance the fake clock properly inside vi.useFakeTimers() tests.
Object.assign(globalThis, { jest: vi })

// jsdom does not implement ResizeObserver; provide a no-op stub so hooks that
// use it (e.g. useScrollSync) do not throw in the test environment.
if (typeof globalThis.ResizeObserver === 'undefined') {
  globalThis.ResizeObserver = class ResizeObserver {
    observe() {}
    unobserve() {}
    disconnect() {}
  }
}

const WARNING_GUARD_KEY = '__agblogger_warning_guard_installed__'
type WarningProcess = {
  on(event: 'warning', listener: (warning: Error) => void): void
}
const nodeProcess = (globalThis as unknown as { process: WarningProcess }).process

if (!(WARNING_GUARD_KEY in globalThis)) {
  Object.defineProperty(globalThis, WARNING_GUARD_KEY, {
    configurable: false,
    enumerable: false,
    value: true,
    writable: false,
  })

  nodeProcess.on('warning', (warning: Error) => {
    throw new Error(
      `Node warning during vitest run (${warning.name}): ${warning.message}\n${warning.stack ?? ''}`,
    )
  })
}

// Fail tests on unexpected console.error / console.warn output.
// Tests that expect console errors should suppress them with:
//   vi.spyOn(console, 'error').mockImplementation(() => {})
const _originalConsoleError = console.error.bind(console)
const _originalConsoleWarn = console.warn.bind(console)
let _collectedErrors: string[] = []

beforeEach(() => {
  _collectedErrors = []
  console.error = (...args: unknown[]) => {
    _collectedErrors.push(args.map(String).join(' '))
  }
  console.warn = (...args: unknown[]) => {
    _collectedErrors.push(args.map(String).join(' '))
  }
})

afterEach(() => {
  console.error = _originalConsoleError
  console.warn = _originalConsoleWarn
  const errors = _collectedErrors
  _collectedErrors = []
  if (errors.length > 0) {
    throw new Error(
      `Test produced unexpected console.error/console.warn output.\n` +
        `Suppress expected output with: vi.spyOn(console, 'error').mockImplementation(() => {})\n\n` +
        errors.join('\n---\n'),
    )
  }
})
