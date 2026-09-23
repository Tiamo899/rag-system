import { http } from './http'
import type {
  PermissionNode,
  Role,
  SystemConfig,
  User,
  UserPage,
} from '../types'

// ---- 用户管理 ----
export async function listUsers(params: {
  page: number
  page_size: number
  search?: string
}): Promise<UserPage> {
  const res = await http.get<UserPage>('/users', { params })
  return res.data
}

export async function createUser(data: {
  username: string
  email: string
  password: string
  role_ids: string[]
  status?: number
}): Promise<User> {
  const res = await http.post<User>('/users', data)
  return res.data
}

export async function updateUser(
  id: string,
  data: Partial<{
    username: string
    email: string
    password: string
    status: number
    role_ids: string[]
  }>
): Promise<User> {
  const res = await http.put<User>(`/users/${id}`, data)
  return res.data
}

export async function deleteUser(id: string): Promise<void> {
  await http.delete(`/users/${id}`)
}

// ---- 角色管理 ----
export async function listRoles(): Promise<Role[]> {
  const res = await http.get<Role[]>('/roles')
  return res.data
}

export async function listRolePermissions(): Promise<PermissionNode[]> {
  const res = await http.get<PermissionNode[]>('/roles/permissions')
  return res.data
}

export async function createRole(data: {
  name: string
  description?: string
  permissions: string[]
}): Promise<Role> {
  const res = await http.post<Role>('/roles', data)
  return res.data
}

export async function updateRole(
  id: string,
  data: Partial<{ name: string; description: string; permissions: string[] }>
): Promise<Role> {
  const res = await http.put<Role>(`/roles/${id}`, data)
  return res.data
}

export async function deleteRole(id: string): Promise<void> {
  await http.delete(`/roles/${id}`)
}

// ---- 系统配置（只读展示）----
export async function listSystemConfigs(): Promise<SystemConfig[]> {
  const res = await http.get<SystemConfig[]>('/system-configs')
  return res.data
}
