import { http } from './http'
import type { DocumentChunk, DocumentItem, KnowledgeBase } from '../types'

export async function listKnowledgeBases(): Promise<KnowledgeBase[]> {
  const res = await http.get<KnowledgeBase[]>('/knowledge-bases')
  return res.data
}

export async function createKnowledgeBase(data: {
  name: string
  description?: string
  visibility?: 'public' | 'restricted'
  allowed_roles?: string[]
  allowed_users?: string[]
}): Promise<KnowledgeBase> {
  const res = await http.post<KnowledgeBase>('/knowledge-bases', data)
  return res.data
}

export async function updateKnowledgeBase(
  id: string,
  data: {
    name?: string
    description?: string
    visibility?: 'public' | 'restricted'
    allowed_roles?: string[]
    allowed_users?: string[]
  }
): Promise<KnowledgeBase> {
  const res = await http.put<KnowledgeBase>(`/knowledge-bases/${id}`, data)
  return res.data
}

export interface KbAccessOptions {
  roles: string[]
  users: { id: string; username: string; email: string }[]
  can_grant_users: boolean
}

export async function fetchKbAccessOptions(): Promise<KbAccessOptions> {
  const res = await http.get<KbAccessOptions>('/knowledge-bases/access-options')
  return res.data
}

export interface UploadDocOptions {
  version_no?: string
  valid_from?: string
  valid_to?: string
  supersedes_doc_id?: string
}

export async function listDocuments(
  kbId: string,
  search?: string,
  activeOnly?: boolean
): Promise<DocumentItem[]> {
  const res = await http.get<DocumentItem[]>(`/knowledge-bases/${kbId}/docs`, {
    params: { search, page_size: 100, active_only: activeOnly || undefined },
  })
  return res.data
}

export async function uploadDocument(
  kbId: string,
  file: File,
  opts?: UploadDocOptions
): Promise<DocumentItem> {
  const form = new FormData()
  form.append('file', file)
  if (opts?.version_no) form.append('version_no', opts.version_no)
  if (opts?.valid_from) form.append('valid_from', opts.valid_from)
  if (opts?.valid_to) form.append('valid_to', opts.valid_to)
  if (opts?.supersedes_doc_id) form.append('supersedes_doc_id', opts.supersedes_doc_id)
  const res = await http.post<DocumentItem>(`/knowledge-bases/${kbId}/docs`, form, {
    headers: { 'Content-Type': 'multipart/form-data' },
  })
  return res.data
}

export async function triggerVectorize(docId: string): Promise<void> {
  await http.post(`/docs/${docId}/vectorize`)
}

export async function fetchChunks(docId: string): Promise<DocumentChunk[]> {
  const res = await http.get<DocumentChunk[]>(`/docs/${docId}/chunks`)
  return res.data
}

export async function deleteDocument(docId: string): Promise<void> {
  await http.delete(`/docs/${docId}`)
}

export async function deleteKnowledgeBase(kbId: string): Promise<void> {
  await http.delete(`/knowledge-bases/${kbId}`)
}
