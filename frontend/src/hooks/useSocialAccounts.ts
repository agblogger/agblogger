import useSWR from 'swr'
import { fetchSocialAccounts } from '@/api/crosspost'
import type { SocialAccount } from '@/api/crosspost'
import { useAuthStore } from '@/stores/authStore'

export function useSocialAccounts() {
  const userId = useAuthStore((state) => state.user?.id ?? null)

  return useSWR<SocialAccount[], Error>(
    userId !== null ? ['crosspost/accounts', userId] : null,
    fetchSocialAccounts,
  )
}
