import useSWR from 'swr'
import { fetchAdminSiteSettings, fetchAdminPages } from '@/api/admin'
import type { AdminSiteSettings, AdminPagesResponse } from '@/api/client'

export function useAdminSiteSettings(enabled = true) {
  return useSWR<AdminSiteSettings, Error>(enabled ? 'admin/site' : null, fetchAdminSiteSettings)
}

export function useAdminPages(enabled = true) {
  return useSWR<AdminPagesResponse, Error>(enabled ? 'admin/pages' : null, fetchAdminPages)
}
