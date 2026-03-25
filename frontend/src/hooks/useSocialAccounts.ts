import useSWR from 'swr'
import { fetchSocialAccounts } from '@/api/crosspost'
import type { SocialAccount } from '@/api/crosspost'

export function useSocialAccounts() {
  return useSWR<SocialAccount[], Error>('crosspost/accounts', fetchSocialAccounts)
}
