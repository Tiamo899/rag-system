import { http } from './http'
import type { ChatMessage, ChatSession, SessionDetail } from '../types'

export async function createSession(data: {
  title?: string
  kb_id?: string
}): Promise<ChatSession> {
  const res = await http.post<ChatSession>('/chat/sessions', data)
  return res.data
}

export async function listSessions(): Promise<ChatSession[]> {
  const res = await http.get<ChatSession[]>('/chat/sessions')
  return res.data
}

export async function getSessionDetail(sessionId: string): Promise<SessionDetail> {
  const res = await http.get<SessionDetail>(`/chat/sessions/${sessionId}`)
  return res.data
}

export async function updateSession(
  sessionId: string,
  data: { title?: string; kb_id?: string }
): Promise<ChatSession> {
  const res = await http.put<ChatSession>(`/chat/sessions/${sessionId}`, data)
  return res.data
}

export async function deleteSession(sessionId: string): Promise<void> {
  await http.delete(`/chat/sessions/${sessionId}`)
}

export async function sendFeedback(
  messageId: string,
  feedback: 'like' | 'dislike' | null
): Promise<ChatMessage> {
  const res = await http.post<ChatMessage>(`/chat/messages/${messageId}/feedback`, {
    feedback,
  })
  return res.data
}
