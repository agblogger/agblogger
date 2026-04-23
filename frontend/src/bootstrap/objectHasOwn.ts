const hasOwnProperty = (target: object, property: PropertyKey): boolean =>
  Object.prototype.hasOwnProperty.call(target, property)

export function installObjectHasOwnCompat(): void {
  if (typeof Object.hasOwn === 'function') {
    return
  }

  Object.defineProperty(Object, 'hasOwn', {
    configurable: true,
    value: hasOwnProperty,
    writable: true,
  })
}
