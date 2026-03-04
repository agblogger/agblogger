import api from './client'
import type { AdminSiteSettings, AdminPageConfig, AdminPagesResponse } from './client'

export async function fetchAdminSiteSettings(): Promise<AdminSiteSettings> {
  return api.get('admin/site').json<AdminSiteSettings>()
}

export async function updateAdminSiteSettings(
  settings: AdminSiteSettings,
): Promise<AdminSiteSettings> {
  return api.put('admin/site', { json: settings }).json<AdminSiteSettings>()
}

export async function fetchAdminPages(): Promise<AdminPagesResponse> {
  return api.get('admin/pages').json<AdminPagesResponse>()
}

export async function createAdminPage(data: {
  id: string
  title: string
}): Promise<AdminPageConfig> {
  return api.post('admin/pages', { json: data }).json<AdminPageConfig>()
}

export async function updateAdminPage(
  pageId: string,
  data: { title?: string; content?: string },
): Promise<void> {
  await api.put(`admin/pages/${pageId}`, { json: data })
}

export async function updateAdminPageOrder(
  pages: { id: string; title: string; file: string | null }[],
): Promise<AdminPagesResponse> {
  return api.put('admin/pages/order', { json: { pages } }).json<AdminPagesResponse>()
}

export async function deleteAdminPage(pageId: string, deleteFile = true): Promise<void> {
  await api.delete(`admin/pages/${pageId}`, {
    searchParams: { delete_file: String(deleteFile) },
  })
}

export async function changeAdminPassword(data: {
  current_password: string
  new_password: string
  confirm_password: string
}): Promise<{ status: string; sessions_revoked?: boolean }> {
  return api.put('admin/password', { json: data }).json<{ status: string; sessions_revoked?: boolean }>()
}
