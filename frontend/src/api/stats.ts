import { http } from './http'
import type { OverviewStats } from '../types'

export async function fetchOverview(): Promise<OverviewStats> {
  const res = await http.get<OverviewStats>('/stats/overview')
  return res.data
}
