import { http } from './http'

export interface TraceHit {
  chunk_id: string
  doc_id: string
  doc_name: string | null
  title: string | null
  chunk_index: number | null
  version_no?: string | null
  valid_from?: string | null
  rank: number | null
  score: number
  preview: string
}

export interface FusedHit extends TraceHit {
  vector_rank: number | null
  keyword_rank: number | null
  rrf_score: number
  rrf_raw: number
  cosine: number
  rrf_ok: boolean
  cos_ok: boolean
}

export interface TraceResult {
  query: string
  search_type: string
  top_k: number
  kb_id: string | null
  rrf_k: number
  embedding: { dim: number; elapsed_ms: number; error: string | null }
  vector: { count: number; error: string | null; hits: TraceHit[] }
  keyword: { count: number; error: string | null; hits: TraceHit[] }
  fusion: {
    thresholds: { rrf: number; cosine: number }
    items: FusedHit[]
  }
  verdict: {
    is_relevant: boolean
    top_rrf: number
    top_cosine: number
    rrf_pass: boolean
    cosine_pass: boolean
    reason: string
  }
  context: string
  degraded: boolean
}

export async function debugSearch(params: {
  query: string
  kb_id?: string | null
  top_k?: number
  search_type?: string
  rrf_threshold?: number
  cos_threshold?: number
}): Promise<TraceResult> {
  const res = await http.post<TraceResult>('/search/debug', params)
  return res.data
}
