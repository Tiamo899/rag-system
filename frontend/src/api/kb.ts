import { http } from './http'
import type { DocumentChunk, DocumentItem, KnowledgeBase } from '../types'

export async function listKnowledgeBases(): Promise<KnowledgeBase[]> {
  const res = await http.get<KnowledgeBase[]>('/knowledge-bases')
  return res.data
}

export async function createKnowledgeBase(data: {
  name: string
  description?: string
}): Promise<KnowledgeBase> {
  const res = await http.post<KnowledgeBase>('/knowledge-bases', data)
  return res.data
}

export async function listDocuments(
  kbId: string,
  search?: string
): Promise<DocumentItem[]> {
  const res = await http.get<DocumentItem[]>(`/knowledge-bases/${kbId}/docs`, {
    params: { search, page_size: 100 },
  })
  return res.data
}

export async function uploadDocument(
  kbId: string,
  file: File
): Promise<DocumentItem> {
  const form = new FormData()
  form.append('file', file)
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
