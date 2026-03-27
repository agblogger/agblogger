/** @type {import('dependency-cruiser').IConfiguration} */
module.exports = {
  options: {
    tsConfig: {
      fileName: 'tsconfig.app.json',
    },
    doNotFollow: {
      path: 'node_modules',
    },
    exclude: {
      path: '(^src/test/)|(__tests__)|(\\.test\\.(ts|tsx)$)',
    },
  },
  forbidden: [
    {
      name: 'no-circular-deps',
      severity: 'error',
      from: { path: '^src' },
      to: { circular: true },
    },
    {
      name: 'no-src-to-tests',
      severity: 'error',
      from: { path: '^src/(?!.*(__tests__|\\.test\\.(ts|tsx)$)).*' },
      to: { path: '__tests__|\\.test\\.(ts|tsx)$' },
    },
    {
      name: 'api-no-ui-or-state',
      severity: 'error',
      from: { path: '^src/api' },
      to: { path: '^src/(components|hooks|pages|stores)' },
    },
    {
      name: 'utils-leaf-layer',
      severity: 'error',
      from: { path: '^src/utils' },
      to: { path: '^src/(api|components|hooks|pages|stores)' },
    },
    {
      name: 'stores-no-ui-or-pages',
      severity: 'error',
      from: { path: '^src/stores' },
      to: { path: '^src/(components|hooks|pages)' },
    },
    {
      name: 'hooks-no-ui-or-pages',
      severity: 'error',
      from: { path: '^src/hooks' },
      to: { path: '^src/(components|pages)' },
    },
    {
      name: 'components-no-pages',
      severity: 'error',
      from: { path: '^src/components' },
      to: { path: '^src/pages' },
    },
    {
      name: 'pages-not-imported-from-lower-layers',
      severity: 'error',
      from: { path: '^src/(api|components|hooks|stores|utils)' },
      to: { path: '^src/pages' },
    },
  ],
}
