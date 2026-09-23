import { useEffect, useRef, useState } from 'react'
import * as echarts from 'echarts'
import {
  Card,
  Col,
  Empty,
  List,
  Row,
  Typography,
  message,
} from 'antd'
import {
  DatabaseOutlined,
  FileTextOutlined,
  LineChartOutlined,
  MessageOutlined,
  PieChartOutlined,
  TeamOutlined,
} from '@ant-design/icons'
import { fetchOverview } from '../api/stats'
import { getErrorMessage } from '../api/http'
import { formatTime } from '../utils/time'
import type { OverviewStats } from '../types'

const CARD_STYLE: React.CSSProperties = {
  borderRadius: 16,
  boxShadow: '0 1px 2px rgba(16,24,40,0.04), 0 10px 28px -14px rgba(16,24,40,0.16)',
}

function useECharts() {
  const chartRef = useRef<echarts.ECharts>()
  const boxRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const chart = chartRef.current
    const onResize = () => chart?.resize()
    window.addEventListener('resize', onResize)
    return () => {
      window.removeEventListener('resize', onResize)
      chart?.dispose()
      chartRef.current = undefined
    }
  }, [])

  return {
    boxRef,
    setOption(option: echarts.EChartsOption) {
      if (!boxRef.current) return
      if (!chartRef.current) chartRef.current = echarts.init(boxRef.current)
      chartRef.current.setOption(option)
    },
  }
}

export default function Dashboard() {
  const [stats, setStats] = useState<OverviewStats | null>(null)
  const pie = useECharts()
  const line = useECharts()

  useEffect(() => {
    fetchOverview()
      .then(setStats)
      .catch((e) => message.error(getErrorMessage(e)))
  }, [])

  useEffect(() => {
    if (!stats) return
    pie.setOption({
      tooltip: { trigger: 'item' },
      legend: { bottom: 0 },
      color: [
        '#6366f1', '#3b82f6', '#22d3ee', '#10b981', '#f59e0b', '#ec4899',
        '#8b5cf6', '#14b8a6', '#f43f5e', '#84cc16', '#6366f1', '#a855f7',
      ],
      series: [
        {
          name: '文档数',
          type: 'pie',
          radius: ['42%', '72%'],
          avoidLabelOverlap: true,
          itemStyle: { borderRadius: 8, borderColor: '#fff', borderWidth: 3 },
          data: stats.kb_distribution.map((d) => ({ name: d.name, value: d.doc_count })),
        },
      ],
    })
    line.setOption({
      tooltip: { trigger: 'axis' },
      grid: { left: 40, right: 20, top: 20, bottom: 30 },
      xAxis: {
        type: 'category',
        boundaryGap: false,
        data: stats.doc_upload_trend.map((d) => d.date.slice(5)),
      },
      yAxis: { type: 'value', minInterval: 1 },
      series: [
        {
          name: '上传文档数',
          type: 'line',
          smooth: true,
          symbolSize: 7,
          lineStyle: { width: 3, color: '#6366f1' },
          itemStyle: { color: '#6366f1', borderColor: '#fff', borderWidth: 2 },
          areaStyle: {
            color: {
              type: 'linear',
              x: 0, y: 0, x2: 0, y2: 1,
              colorStops: [
                { offset: 0, color: 'rgba(99,102,241,0.32)' },
                { offset: 1, color: 'rgba(99,102,241,0.02)' },
              ],
            },
          },
          data: stats.doc_upload_trend.map((d) => d.count),
        },
      ],
    })
  }, [stats, pie, line])

  const cards = [
    { title: '知识库', value: stats?.kb_total ?? 0, icon: <DatabaseOutlined />, gradient: 'linear-gradient(135deg,#6366f1,#818cf8)' },
    { title: '文档', value: stats?.doc_total ?? 0, icon: <FileTextOutlined />, gradient: 'linear-gradient(135deg,#3b82f6,#60a5fa)' },
    { title: '用户', value: stats?.user_total ?? 0, icon: <TeamOutlined />, gradient: 'linear-gradient(135deg,#f59e0b,#fbbf24)' },
    { title: '今日对话', value: stats?.today_chat_count ?? 0, icon: <MessageOutlined />, gradient: 'linear-gradient(135deg,#10b981,#34d399)' },
  ]

  return (
    <div>
      <Row gutter={[16, 16]}>
        {cards.map((c) => (
          <Col span={6} key={c.title}>
            <Card className="stat-card lift-card" style={CARD_STYLE}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
                <span
                  className="stat-icon"
                  style={{
                    width: 52,
                    height: 52,
                    borderRadius: 14,
                    background: c.gradient,
                    display: 'inline-flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    fontSize: 23,
                    color: '#fff',
                    flexShrink: 0,
                  }}
                >
                  {c.icon}
                </span>
                <div>
                  <div style={{ color: '#64748b', fontSize: 13, marginBottom: 2 }}>{c.title}</div>
                  <div style={{ fontSize: 28, fontWeight: 800, color: '#0f172a', lineHeight: 1.15, letterSpacing: 0.3 }}>
                    {c.value}
                  </div>
                </div>
              </div>
            </Card>
          </Col>
        ))}
      </Row>

      <Row gutter={16} style={{ marginTop: 16 }}>
        <Col span={12}>
          <Card
            title={
              <span>
                <MessageOutlined style={{ color: '#6366f1', marginRight: 8 }} />
                最近对话
              </span>
            }
            style={CARD_STYLE}
            styles={{ body: { paddingTop: 8 } }}
          >
            {stats && stats.recent_sessions.length > 0 ? (
              <List
                dataSource={stats.recent_sessions}
                renderItem={(s) => (
                  <List.Item>
                    <List.Item.Meta
                      avatar={
                        <span
                          style={{
                            width: 36,
                            height: 36,
                            borderRadius: 10,
                            background: 'rgba(99,102,241,0.12)',
                            display: 'inline-flex',
                            alignItems: 'center',
                            justifyContent: 'center',
                            color: '#6366f1',
                            fontSize: 16,
                          }}
                        >
                          <MessageOutlined />
                        </span>
                      }
                      title={s.title || '新对话'}
                      description={s.preview || '（暂无消息）'}
                    />
                    <Typography.Text type="secondary" style={{ whiteSpace: 'nowrap', fontSize: 12 }}>
                      {formatTime(s.updated_at)}
                    </Typography.Text>
                  </List.Item>
                )}
              />
            ) : (
              <Empty description="暂无对话记录" />
            )}
          </Card>
        </Col>
        <Col span={12}>
          <Card
            title={
              <span>
                <PieChartOutlined style={{ color: '#6366f1', marginRight: 8 }} />
                知识库分布
              </span>
            }
            style={CARD_STYLE}
          >
            <div ref={pie.boxRef} style={{ height: 300 }} />
          </Card>
        </Col>
      </Row>

      <Card
        title={
          <span>
            <LineChartOutlined style={{ color: '#6366f1', marginRight: 8 }} />
            近 7 天文档上传趋势
          </span>
        }
        style={{ ...CARD_STYLE, marginTop: 16 }}
      >
        <div ref={line.boxRef} style={{ height: 300 }} />
      </Card>
    </div>
  )
}
