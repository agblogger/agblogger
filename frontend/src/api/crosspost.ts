import api from './client'

export interface SocialAccount {
  id: number
  platform: string
  account_name: string | null
  created_at: string
}

export type CrossPostStatus = 'pending' | 'posted' | 'failed'

export interface CrossPostResult {
  id: number
  post_path: string
  platform: string
  platform_id: string | null
  status: CrossPostStatus
  posted_at: string | null
  error: string | null
}

export interface CrossPostHistory {
  items: CrossPostResult[]
}

export async function fetchSocialAccounts(): Promise<SocialAccount[]> {
  return api.get('crosspost/accounts').json<SocialAccount[]>()
}

export async function deleteSocialAccount(accountId: number): Promise<void> {
  await api.delete(`crosspost/accounts/${accountId}`)
}

export async function authorizeBluesky(
  handle: string,
): Promise<{ authorization_url: string }> {
  return api
    .post('crosspost/bluesky/authorize', { json: { handle } })
    .json<{ authorization_url: string }>()
}

export async function authorizeMastodon(
  instanceUrl: string,
): Promise<{ authorization_url: string }> {
  return api
    .post('crosspost/mastodon/authorize', { json: { instance_url: instanceUrl } })
    .json<{ authorization_url: string }>()
}

export async function authorizeX(): Promise<{ authorization_url: string }> {
  return api
    .post('crosspost/x/authorize')
    .json<{ authorization_url: string }>()
}

export async function authorizeFacebook(): Promise<{ authorization_url: string }> {
  return api
    .post('crosspost/facebook/authorize')
    .json<{ authorization_url: string }>()
}

export interface FacebookPage {
  id: string
  name: string
}

export async function fetchFacebookPages(state: string): Promise<FacebookPage[]> {
  const resp = await api
    .get('crosspost/facebook/pages', { searchParams: { state } })
    .json<{ pages: FacebookPage[] }>()
  return resp.pages
}

export async function selectFacebookPage(
  state: string,
  pageId: string,
): Promise<{ account_name: string }> {
  return api
    .post('crosspost/facebook/select-page', {
      json: { state, page_id: pageId },
    })
    .json<{ account_name: string }>()
}

export async function crossPost(
  postPath: string,
  platforms: string[],
  customText?: string,
): Promise<CrossPostResult[]> {
  return api
    .post('crosspost/post', {
      json: { post_path: postPath, platforms, custom_text: customText ?? null },
    })
    .json<CrossPostResult[]>()
}

export async function fetchCrossPostHistory(
  postPath: string,
): Promise<CrossPostHistory> {
  return api.get(`crosspost/history/${postPath}`).json<CrossPostHistory>()
}
