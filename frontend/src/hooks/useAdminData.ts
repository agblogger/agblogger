import useSWR from 'swr'
import { fetchAdminSiteSettings, fetchAdminPages } from '@/api/admin'
import type { AdminSiteSettings, AdminPagesResponse } from '@/api/client'

export function useAdminSiteSettings() {
  return useSWR<AdminSiteSettings>('admin/site', fetchAdminSiteSettings)
}

export function useAdminPages() {
  return useSWR<AdminPagesResponse>('admin/pages', fetchAdminPages)
}
