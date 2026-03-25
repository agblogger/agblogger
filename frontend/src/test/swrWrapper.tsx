import { SWRConfig } from 'swr'
import type { ReactNode } from 'react'

export function SWRTestWrapper({ children }: { children: ReactNode }) {
  return (
    <SWRConfig value={{ provider: () => new Map(), dedupingInterval: 0 }}>
      {children}
    </SWRConfig>
  )
}
