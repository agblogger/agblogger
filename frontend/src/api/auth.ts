import api, { clearCsrfToken, primeCsrfToken } from './client'
import type { SessionAuthResponse, UserResponse } from './client'

export async function login(username: string, password: string): Promise<SessionAuthResponse> {
  const response = await api
    .post('auth/login', { json: { username, password } })
    .json<SessionAuthResponse>()
  primeCsrfToken(response.csrf_token)
  return response
}

export async function register(
  username: string,
  email: string,
  password: string,
  displayName?: string,
): Promise<UserResponse> {
  return api
    .post('auth/register', {
      json: { username, email, password, display_name: displayName },
    })
    .json<UserResponse>()
}

export async function fetchMe(): Promise<UserResponse> {
  return api.get('auth/me').json<UserResponse>()
}

export async function logout(): Promise<void> {
  try {
    await api.post('auth/logout', { json: {} })
  } finally {
    clearCsrfToken()
  }
}
