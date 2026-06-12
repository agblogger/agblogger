import api from './client'

export interface SubscribeResponse {
  message: string
}

export interface SubscriptionSettings {
  enabled: boolean
  from_email: string | null
  from_name: string | null
  controller_name: string | null
  controller_contact: string | null
  privacy_policy_url: string | null
  postal_address: string | null
  key_configured: boolean
  webhook_secret_configured: boolean
  segment_configured: boolean
  subscriber_count: number | null
}

export interface SubscriptionSettingsUpdate {
  enabled?: boolean
  api_key?: string
  from_email?: string | null
  from_name?: string | null
  controller_name?: string | null
  controller_contact?: string | null
  privacy_policy_url?: string | null
  postal_address?: string | null
}

export type BroadcastStatus = 'sent' | 'failed'
export type BroadcastTrigger = 'auto' | 'manual'

export interface BroadcastSummary {
  id: number
  request_id?: string | null
  post_path: string
  post_title: string
  resend_broadcast_id: string | null
  trigger: BroadcastTrigger
  status: BroadcastStatus
  sent_at: string
  error: string | null
}

export async function subscribe(email: string): Promise<SubscribeResponse> {
  return api.post('subscribe', { json: { email } }).json<SubscribeResponse>()
}

export async function fetchSubscriptionSettings(): Promise<SubscriptionSettings> {
  return api.get('admin/subscriptions/settings').json<SubscriptionSettings>()
}

export async function updateSubscriptionSettings(
  patch: SubscriptionSettingsUpdate,
): Promise<SubscriptionSettings> {
  return api.put('admin/subscriptions/settings', { json: patch }).json<SubscriptionSettings>()
}

export async function sendTestEmail(email: string): Promise<{ message: string }> {
  return api.post('admin/subscriptions/test', { json: { email } }).json<{ message: string }>()
}

export async function fetchBroadcasts(): Promise<{ broadcasts: BroadcastSummary[] }> {
  return api.get('admin/subscriptions/broadcasts').json<{ broadcasts: BroadcastSummary[] }>()
}

export async function triggerBroadcast(
  postPath: string,
): Promise<{ message: string; request_id: string }> {
  return api
    .post('admin/subscriptions/broadcasts', { json: { post_path: postPath } })
    .json<{ message: string; request_id: string }>()
}
