// 与后端 schema 对齐的类型定义
export interface User {
  id: string
  username: string
  email: string
  status: number
  roles: string[]
  role_ids: string[]
  created_at: string
}

export interface TokenResponse {
  access_token: string
  refresh_token: string
  token_type: string
  user: User
}

export interface KnowledgeBase {
  id: string
  name: string
  description?: string | null
  icon?: string
  color?: string
  chunk_size: number
  chunk_overlap: number
  status: number
  created_at: string
}

export type DocStatus = 'pending' | 'processing' | 'completed' | 'failed'

export interface DocumentItem {
  id: string
  kb_id: string
  filename: string
  original_name: string
  file_type: string
  file_size?: number | null
  status: DocStatus
  chunk_count: number
  created_at: string
}

export interface DocumentChunk {
  id: string
  doc_id: string
  title?: string | null
  chunk_index: number
  content: string
  token_count?: number | null
  es_doc_id?: string | null
}

export interface ChatSession {
  id: string
  title: string
  kb_id?: string | null
  status: number
  created_at: string
  updated_at: string
}

export interface ChatMessage {
  id: string
  session_id: string
  role: 'user' | 'assistant' | 'system'
  content: string
  sources: Source[]
  model?: string | null
  feedback?: 'like' | 'dislike' | null
  created_at: string
}

export interface Source {
  chunk_id?: string
  doc_id: string
  doc_name?: string | null
  kb_name?: string | null
  title?: string | null
  chunk_index?: number
  content: string
  score: number
}

export interface SessionDetail {
  session: ChatSession
  messages: ChatMessage[]
}

// ---- 管理端 ----
export interface Role {
  id: string
  name: string
  description?: string | null
  permissions: string[]
  user_count: number
  created_at: string
  updated_at: string
}

export interface PermissionNode {
  module: string
  key: string
  permissions: { key: string; label: string }[]
}

export interface UserPage {
  items: User[]
  total: number
  page: number
  page_size: number
}

export interface SystemConfig {
  id?: string | null
  key: string
  value?: string | null
  description?: string | null
  env_key?: string | null
  source?: string
  updated_at?: string | null
}

// ---- 概览大屏 ----
export interface RecentSessionStat {
  id: string
  title: string
  updated_at: string
  preview: string
}

export interface KBStat {
  name: string
  doc_count: number
}

export interface DailyStat {
  date: string
  count: number
}

export interface OverviewStats {
  kb_total: number
  doc_total: number
  user_total: number
  today_chat_count: number
  recent_sessions: RecentSessionStat[]
  kb_distribution: KBStat[]
  doc_upload_trend: DailyStat[]
}
