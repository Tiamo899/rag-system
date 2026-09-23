/**
 * 把后端返回的 ISO 时间（UTC，带 Z）格式化为北京时间（UTC+8）字符串 YYYY-MM-DD HH:mm。
 * 固定 +8 偏移，不随浏览器时区变化。
 */
export function formatTime(iso: string): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  const bj = new Date(d.getTime() + 8 * 3600 * 1000)
  const pad = (n: number) => String(n).padStart(2, '0')
  return (
    `${bj.getUTCFullYear()}-${pad(bj.getUTCMonth() + 1)}-${pad(bj.getUTCDate())} ` +
    `${pad(bj.getUTCHours())}:${pad(bj.getUTCMinutes())}`
  )
}
