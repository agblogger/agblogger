import { afterEach, describe, expect, it } from 'vitest'

import { installObjectHasOwnCompat } from '@/bootstrap/objectHasOwn'

const originalDescriptor = Object.getOwnPropertyDescriptor(Object, 'hasOwn')

afterEach(() => {
  if (originalDescriptor === undefined) {
    Reflect.deleteProperty(Object, 'hasOwn')
    return
  }

  Object.defineProperty(Object, 'hasOwn', originalDescriptor)
})

describe('installObjectHasOwnCompat', () => {
  it('installs a fallback when Object.hasOwn is unavailable', () => {
    Reflect.deleteProperty(Object, 'hasOwn')

    installObjectHasOwnCompat()

    expect(typeof Object.hasOwn).toBe('function')
    expect(Object.hasOwn({ visible: true }, 'visible')).toBe(true)
    expect(Object.hasOwn({ visible: true }, 'missing')).toBe(false)

    const nullPrototypeRecord = Object.create(null) as { visible?: boolean }
    nullPrototypeRecord.visible = true
    expect(Object.hasOwn(nullPrototypeRecord, 'visible')).toBe(true)
  })

  it('does not replace an existing implementation', () => {
    const sentinel = () => true
    Object.defineProperty(Object, 'hasOwn', {
      configurable: true,
      value: sentinel,
      writable: true,
    })

    installObjectHasOwnCompat()

    expect(Object.hasOwn).toBe(sentinel)
  })
})
