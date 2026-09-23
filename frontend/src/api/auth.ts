import { http } from './http'
import type { TokenResponse, User } from '../types'

export async function login(username: string, password: string): Promise<TokenResponse> {
  const res = await http.post<TokenResponse>('/auth/login', { username, password })
  return res.data
}

export async function fetchMe(): Promise<User> {
  const res = await http.get<User>('/auth/me')
  return res.data
}
