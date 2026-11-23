import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  Alert,
  Button,
  Card,
  Col,
  Empty,
  Input,
  InputNumber,
  Progress,
  Row,
  Segmented,
  Select,
  Space,
  Table,
  Tag,
  Tooltip,
  Typography,
} from 'antd'
import {
  ApiOutlined,
  BranchesOutlined,
  ExperimentOutlined,
  FileTextOutlined,
  SearchOutlined,
  ThunderboltOutlined,
} from '@ant-design/icons'
import { listKnowledgeBases } from '../api/kb'
import { debugSearch } from '../api/search'
import type { FusedHit, TraceHit, TraceResult } from '../api/search'
import type { KnowledgeBase } from '../types'

const { Text, Title } = Typography

const EXAMPLES = [
  '挂科了还能评奖学金吗',
  '转专业需要什么条件',
  '国家助学金什么时候申请',
  '补考不过可以重修几次',
  '每学期最少要选多少学分',
]

const COLORS = {
  vector: '#6366f1',
  keyword: '#0ea5e9',
  pass: '#16a34a',
  fail: '#dc2626',
}

function ScoreBar({ value, max, color }: { value: number; max: number; color: string }) {
  const pct = max > 0 ? Math.min(100, (value / max) * 100) : 0
  return (
    <div
      style={{
        height: 4,
        borderRadius: 3,
        background: '#eef2f7',
        overflow: 'hidden',
        marginTop: 4,
      }}
    >
      <div style={{ width: `${pct}%`, height: '100%', background: color, borderRadius: 3 }} />
    </div>
  )
}

function HitTable({
  hits,
  color,
  emptyText,
}: {
  hits: TraceHit[]
  color: string
  emptyText: string
}) {
  const maxScore = Math.max(...hits.map((h) => h.score), 0.000001)
  const columns = [
    {
      title: '#',
      dataIndex: 'rank',
      width: 42,
      render: (v: number) => (
        <span
          style={{
            display: 'inline-flex',
            width: 22,
            height: 22,
            borderRadius: 11,
            alignItems: 'center',
            justifyContent: 'center',
            fontSize: 11.5,
            fontWeight: 700,
            color: '#fff',
            background: v <= 3 ? color : '#94a3b8',
          }}
        >
          {v}
        </span>
      ),
    },
    {
      title: '命中分块',
      dataIndex: 'title',
      render: (_: unknown, r: TraceHit) => (
        <div>
          <div style={{ fontWeight: 600, color: '#0f172a', fontSize: 13 }}>
            {r.title || '（无标题）'}
          </div>
          <div style={{ color: '#64748b', fontSize: 12, marginTop: 2 }}>
            {r.doc_name ?? '未知文档'}
            {r.version_no ? ` · ${r.version_no}` : ''}
          </div>
          <div style={{ color: '#94a3b8', fontSize: 11.5, marginTop: 3, lineHeight: 1.5 }}>
            {r.preview}
          </div>
        </div>
      ),
    },
    {
      title: '分数',
      dataIndex: 'score',
      width: 96,
      align: 'right' as const,
      render: (v: number) => (
        <div>
          <span style={{ fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace', fontSize: 12 }}>
            {v.toFixed(4)}
          </span>
          <ScoreBar value={v} max={maxScore} color={color} />
        </div>
      ),
    },
  ]
  if (!hits.length) return <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={emptyText} />
  return (
    <Table
      rowKey={(r) => `${r.chunk_id}-${r.rank}`}
      size="small"
      pagination={false}
      columns={columns}
      dataSource={hits}
      scroll={{ y: 300 }}
    />
  )
}

export default function SearchDebug() {
  const [kbs, setKbs] = useState<KnowledgeBase[]>([])
  const [kbId, setKbId] = useState<string | undefined>(undefined)
  const [query, setQuery] = useState('挂科了还能评奖学金吗')
  const [topK, setTopK] = useState(5)
  const [searchType, setSearchType] = useState<'hybrid' | 'vector' | 'keyword'>('hybrid')
  const [rrfTh, setRrfTh] = useState<number>(0.02)
  const [cosTh, setCosTh] = useState<number>(0.5)
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState<TraceResult | null>(null)
  const [err, setErr] = useState<string | null>(null)

  useEffect(() => {
    listKnowledgeBases()
      .then(setKbs)
      .catch(() => undefined)
  }, [])

  const run = useCallback(
    async (override?: { q?: string }) => {
      const q = (override?.q ?? query).trim()
      if (!q) return
      setLoading(true)
      setErr(null)
      try {
        const data = await debugSearch({
          query: q,
          kb_id: kbId ?? null,
          top_k: topK,
          search_type: searchType,
          rrf_threshold: rrfTh,
          cos_threshold: cosTh,
        })
        setResult(data)
      } catch (e: unknown) {
        const msg = e instanceof Error ? e.message : '检索失败'
        setErr(msg)
      } finally {
        setLoading(false)
      }
    },
    [query, kbId, topK, searchType, rrfTh, cosTh]
  )

  useEffect(() => {
    run()
    // 首次进入自动跑一次，页面直接有内容可看
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const fusedColumns = useMemo(
    () => [
      {
        title: '#',
        width: 44,
        render: (_: unknown, __: FusedHit, i: number) => (
          <span style={{ fontWeight: 700, color: i < 3 ? COLORS.vector : '#94a3b8' }}>{i + 1}</span>
        ),
      },
      {
        title: '分块',
        render: (_: unknown, r: FusedHit) => (
          <div>
            <div style={{ fontWeight: 600, fontSize: 13, color: '#0f172a' }}>{r.title || '（无标题）'}</div>
            <div style={{ fontSize: 12, color: '#64748b' }}>{r.doc_name}</div>
          </div>
        ),
      },
      {
        title: '向量排名',
        dataIndex: 'vector_rank',
        width: 88,
        align: 'center' as const,
        render: (v: number | null) =>
          v ? <Tag color="geekblue">#{v}</Tag> : <Text type="secondary">—</Text>,
      },
      {
        title: 'BM25 排名',
        dataIndex: 'keyword_rank',
        width: 94,
        align: 'center' as const,
        render: (v: number | null) =>
          v ? <Tag color="cyan">#{v}</Tag> : <Text type="secondary">—</Text>,
      },
      {
        title: 'RRF 分',
        dataIndex: 'rrf_score',
        width: 96,
        align: 'right' as const,
        render: (v: number, r: FusedHit) => (
          <Tooltip title={`1/(k+rank) 累加，k=${60}；阈值 ${r.rrf_ok ? '已达标' : '未达标'}`}>
            <span
              style={{
                fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace',
                fontSize: 12,
                color: r.rrf_ok ? COLORS.pass : '#475569',
                fontWeight: 600,
              }}
            >
              {v.toFixed(4)}
            </span>
          </Tooltip>
        ),
      },
      {
        title: '余弦',
        dataIndex: 'cosine',
        width: 88,
        align: 'right' as const,
        render: (v: number, r: FusedHit) => (
          <span
            style={{
              fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace',
              fontSize: 12,
              color: r.cos_ok ? COLORS.pass : '#475569',
              fontWeight: 600,
            }}
          >
            {v.toFixed(3)}
          </span>
        ),
      },
      {
        title: '判定',
        width: 96,
        align: 'center' as const,
        render: (_: unknown, r: FusedHit) => {
          if (result?.degraded) return <Tag color="warning" bordered={false}>降级·关键词</Tag>
          return r.rrf_ok || r.cos_ok ? (
            <Tag color="success" bordered={false}>
              相关{r.rrf_ok ? '·RRF' : ''}
              {r.cos_ok ? '·余弦' : ''}
            </Tag>
          ) : (
            <Tag color="default" bordered={false}>
              未达标
            </Tag>
          )
        },
      },
    ],
    [result?.degraded]
  )

  const verdict = result?.verdict
  const rrfPct = result && verdict ? Math.min(100, (verdict.top_rrf / Math.max(result.fusion.thresholds.rrf, 1e-6)) * 100) : 0
  const cosPct = result && verdict ? Math.max(0, verdict.top_cosine * 100) : 0

  return (
    <div style={{ padding: '4px 4px 24px' }}>
      <Card className="lift-card" style={{ borderRadius: 16, marginBottom: 16 }} bodyStyle={{ padding: '18px 20px' }}>
        <Row gutter={16} align="middle">
          <Col flex="auto">
            <Space align="center" size={10}>
              <span
                style={{
                  width: 34,
                  height: 34,
                  borderRadius: 10,
                  display: 'inline-flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  background: 'var(--brand-soft)',
                  color: 'var(--brand-600)',
                  fontSize: 17,
                }}
              >
                <ExperimentOutlined />
              </span>
              <div>
                <Title level={5} style={{ margin: 0, color: '#0f172a' }}>
                  检索链路调试台
                </Title>
                <Text style={{ color: '#64748b', fontSize: 12.5 }}>
                  双路召回 → RRF 融合 → 余弦校验 → 阈值判定 → 上下文拼装，全流程可视
                </Text>
              </div>
            </Space>
          </Col>
          <Col>
            <Space size={8}>
              <Tag color="geekblue" bordered={false}>
                <ApiOutlined /> 向量 kNN
              </Tag>
              <Tag color="cyan" bordered={false}>
                <SearchOutlined /> BM25 · IK
              </Tag>
              <Tag color="purple" bordered={false}>
                <BranchesOutlined /> RRF k={result?.rrf_k ?? 60}
              </Tag>
            </Space>
          </Col>
        </Row>

        <Row gutter={[12, 12]} style={{ marginTop: 16 }} align="middle">
          <Col xs={24} md={13}>
            <Input
              size="large"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onPressEnter={() => run()}
              placeholder="输入学生口语化问题，例如“挂科了还能评奖学金吗”"
              prefix={<SearchOutlined style={{ color: '#94a3b8' }} />}
              allowClear
            />
          </Col>
          <Col xs={24} md={11}>
            <Select
              size="large"
              style={{ width: '100%' }}
              placeholder="全库检索（不选知识库）"
              allowClear
              value={kbId}
              onChange={setKbId}
              options={kbs.map((k) => ({ label: k.name, value: k.id }))}
            />
          </Col>
        </Row>

        <Row gutter={[12, 12]} style={{ marginTop: 12 }} align="middle">
          <Col xs={24} md={8}>
            <Segmented
              block
              size="large"
              value={searchType}
              onChange={(v) => setSearchType(v as typeof searchType)}
              options={[
                { label: '混合检索', value: 'hybrid' },
                { label: '仅向量', value: 'vector' },
                { label: '仅关键词', value: 'keyword' },
              ]}
            />
          </Col>
          <Col xs={12} md={3}>
            <Space direction="vertical" size={2} style={{ width: '100%' }}>
              <Text style={{ fontSize: 12, color: '#64748b' }}>top_k</Text>
              <InputNumber
                size="middle"
                min={1}
                max={20}
                value={topK}
                onChange={(v) => setTopK(Number(v ?? 5))}
                style={{ width: '100%' }}
              />
            </Space>
          </Col>
          <Col xs={12} md={3}>
            <Space direction="vertical" size={2} style={{ width: '100%' }}>
              <Text style={{ fontSize: 12, color: '#64748b' }}>RRF 阈值</Text>
              <InputNumber
                size="middle"
                step={0.005}
                min={0}
                max={1}
                value={rrfTh}
                onChange={(v) => setRrfTh(Number(v ?? 0))}
                style={{ width: '100%' }}
              />
            </Space>
          </Col>
          <Col xs={12} md={3}>
            <Space direction="vertical" size={2} style={{ width: '100%' }}>
              <Text style={{ fontSize: 12, color: '#64748b' }}>余弦阈值</Text>
              <InputNumber
                size="middle"
                step={0.05}
                min={-1}
                max={1}
                value={cosTh}
                onChange={(v) => setCosTh(Number(v ?? 0))}
                style={{ width: '100%' }}
              />
            </Space>
          </Col>
          <Col xs={12} md={7}>
            <Space direction="vertical" size={2} style={{ width: '100%' }}>
              <Text style={{ fontSize: 12, color: 'transparent' }}>&nbsp;</Text>
              <Button
                type="primary"
                size="middle"
                block
                loading={loading}
                icon={<ThunderboltOutlined />}
                onClick={() => run()}
              >
                执行检索
              </Button>
            </Space>
          </Col>
        </Row>

        <Space size={6} wrap style={{ marginTop: 12 }}>
          <Text style={{ fontSize: 12.5, color: '#94a3b8' }}>示例：</Text>
          {EXAMPLES.map((s) => (
            <Tag
              key={s}
              bordered={false}
              style={{ cursor: 'pointer', background: '#f1f5f9', color: '#475569', borderRadius: 12 }}
              onClick={() => {
                setQuery(s)
                run({ q: s })
              }}
            >
              {s}
            </Tag>
          ))}
        </Space>
      </Card>

      {err && (
        <Alert
          type="error"
          showIcon
          style={{ marginBottom: 16, borderRadius: 12 }}
          message="检索失败"
          description={err}
        />
      )}

      {result?.degraded && (
        <Alert
          type="warning"
          showIcon
          style={{ marginBottom: 16, borderRadius: 12 }}
          message="向量服务不可用，已自动降级为关键词检索"
          description={`${result.embedding.error ?? ''}　服务未中断，仍可基于 BM25 命中作答。`}
        />
      )}

      {result && (
        <>
          <Row gutter={16} style={{ marginBottom: 16 }}>
            {[
              {
                title: '向量召回',
                icon: <ApiOutlined />,
                value: result.vector.count,
                unit: '条',
                sub: result.embedding.error
                  ? '向量服务异常'
                  : `${result.embedding.dim} 维 · ${result.embedding.elapsed_ms}ms`,
                color: COLORS.vector,
              },
              {
                title: 'BM25 召回',
                icon: <SearchOutlined />,
                value: result.keyword.count,
                unit: '条',
                sub: result.keyword.error ? '关键词服务异常' : 'IK 分词 · BM25',
                color: COLORS.keyword,
              },
              {
                title: 'Top1 RRF',
                icon: <BranchesOutlined />,
                value: result.verdict.top_rrf.toFixed(4),
                unit: '',
                sub: `阈值 ${result.fusion.thresholds.rrf}`,
                color: result.verdict.rrf_pass ? COLORS.pass : COLORS.fail,
              },
              {
                title: 'Top1 余弦',
                icon: <ExperimentOutlined />,
                value: result.verdict.top_cosine.toFixed(3),
                unit: '',
                sub: `阈值 ${result.fusion.thresholds.cosine}`,
                color: result.verdict.cosine_pass ? COLORS.pass : COLORS.fail,
              },
            ].map((c) => (
              <Col xs={12} md={6} key={c.title}>
                <Card className="stat-card lift-card" style={{ borderRadius: 14 }} bodyStyle={{ padding: '14px 16px' }}>
                  <Space size={8} align="start">
                    <span
                      style={{
                        width: 30,
                        height: 30,
                        borderRadius: 9,
                        background: '#f8fafc',
                        color: c.color,
                        display: 'inline-flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        fontSize: 15,
                      }}
                    >
                      {c.icon}
                    </span>
                    <div>
                      <div style={{ fontSize: 12, color: '#64748b' }}>{c.title}</div>
                      <div style={{ fontSize: 22, fontWeight: 700, color: c.color, lineHeight: 1.3 }}>
                        {c.value}
                        <span style={{ fontSize: 12, fontWeight: 500, marginLeft: 3, color: '#94a3b8' }}>{c.unit}</span>
                      </div>
                      <div style={{ fontSize: 11.5, color: '#94a3b8' }}>{c.sub}</div>
                    </div>
                  </Space>
                </Card>
              </Col>
            ))}
          </Row>

          <Row gutter={16}>
            <Col xs={24} xl={14}>
              <Card
                className="lift-card"
                style={{ borderRadius: 16, marginBottom: 16 }}
                title={
                  <Space>
                    <span style={{ color: COLORS.vector }}>
                      <ApiOutlined />
                    </span>
                    <span>① 向量路召回（kNN · HNSW）</span>
                    <Tag bordered={false}>{result.vector.count}</Tag>
                  </Space>
                }
              >
                <HitTable
                  hits={result.vector.hits}
                  color={COLORS.vector}
                  emptyText={result.embedding.error ? '向量服务不可用' : '无向量召回结果'}
                />
              </Card>

              <Card
                className="lift-card"
                style={{ borderRadius: 16, marginBottom: 16 }}
                title={
                  <Space>
                    <span style={{ color: COLORS.keyword }}>
                      <SearchOutlined />
                    </span>
                    <span>② 关键词路召回（IK + BM25）</span>
                    <Tag bordered={false}>{result.keyword.count}</Tag>
                  </Space>
                }
              >
                <HitTable
                  hits={result.keyword.hits}
                  color={COLORS.keyword}
                  emptyText="无关键词召回结果"
                />
              </Card>
            </Col>

            <Col xs={24} xl={10}>
              <Card
                className="lift-card"
                style={{ borderRadius: 16, marginBottom: 16 }}
                title={
                  <Space>
                    <span style={{ color: COLORS.pass }}>
                      <BranchesOutlined />
                    </span>
                    <span>③ 判定过程</span>
                  </Space>
                }
              >
                <div style={{ marginBottom: 18 }}>
                  <Space style={{ width: '100%', justifyContent: 'space-between' }}>
                    <Text style={{ fontSize: 13, fontWeight: 600 }}>RRF 融合分（取或判据之一）</Text>
                    <Tag color={result.verdict.rrf_pass ? 'success' : 'error'} bordered={false}>
                      {result.verdict.top_rrf.toFixed(4)} / {result.fusion.thresholds.rrf}
                    </Tag>
                  </Space>
                  <Progress
                    percent={Math.round(rrfPct)}
                    showInfo={false}
                    strokeColor={result.verdict.rrf_pass ? COLORS.pass : COLORS.fail}
                    trailColor="#eef2f7"
                    strokeWidth={8}
                    style={{ width: '100%' }}
                  />
                  <Text style={{ fontSize: 11.5, color: '#94a3b8' }}>
                    分数量级随候选集变化，单用此判据易误杀真相关内容
                  </Text>
                </div>

                <div style={{ marginBottom: 18 }}>
                  <Space style={{ width: '100%', justifyContent: 'space-between' }}>
                    <Text style={{ fontSize: 13, fontWeight: 600 }}>余弦相似度（绝对量纲兜底）</Text>
                    <Tag color={result.verdict.cosine_pass ? 'success' : 'error'} bordered={false}>
                      {result.verdict.top_cosine.toFixed(3)} / {result.fusion.thresholds.cosine}
                    </Tag>
                  </Space>
                  <Progress
                    percent={Math.round(cosPct)}
                    showInfo={false}
                    strokeColor={result.verdict.cosine_pass ? COLORS.pass : COLORS.fail}
                    trailColor="#eef2f7"
                    strokeWidth={8}
                    style={{ width: '100%' }}
                  />
                  <Text style={{ fontSize: 11.5, color: '#94a3b8' }}>
                    与问句向量的语义贴合度，独立于候选集规模
                  </Text>
                </div>

                <div
                  style={{
                    padding: '12px 14px',
                    borderRadius: 12,
                    background: result.verdict.is_relevant ? '#f0fdf4' : '#fef2f2',
                    border: `1px solid ${result.verdict.is_relevant ? '#bbf7d0' : '#fecaca'}`,
                  }}
                >
                  <Space direction="vertical" size={4}>
                    <Tag
                      color={result.verdict.is_relevant ? 'success' : 'error'}
                      bordered={false}
                      style={{ fontWeight: 600 }}
                    >
                      {result.verdict.is_relevant ? '判定：相关，进入生成' : '判定：不相关，走兜底'}
                    </Tag>
                    <Text style={{ fontSize: 12.5, color: '#475569' }}>{result.verdict.reason}</Text>
                  </Space>
                </div>
              </Card>

              <Card
                className="lift-card"
                style={{ borderRadius: 16, marginBottom: 16 }}
                title={
                  <Space>
                    <span style={{ color: '#8b5cf6' }}>
                      <FileTextOutlined />
                    </span>
                    <span>④ 上下文拼装预览</span>
                  </Space>
                }
              >
                {result.context ? (
                  <pre
                    style={{
                      margin: 0,
                      whiteSpace: 'pre-wrap',
                      wordBreak: 'break-word',
                      fontSize: 12.5,
                      lineHeight: 1.7,
                      color: '#334155',
                      background: '#f8fafc',
                      border: '1px solid #eef2f7',
                      borderRadius: 10,
                      padding: '12px 14px',
                      maxHeight: 260,
                      overflow: 'auto',
                      fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace',
                    }}
                  >
                    {result.context}
                  </pre>
                ) : (
                  <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="判定不相关，上下文为空" />
                )}
              </Card>
            </Col>
          </Row>

          <Card
            className="lift-card"
            style={{ borderRadius: 16 }}
            title={
              <Space>
                <span style={{ color: COLORS.vector }}>
                  <BranchesOutlined />
                </span>
                <span>RRF 融合结果（前 {result.fusion.items.length} 条）</span>
                <Text style={{ fontSize: 12, color: '#94a3b8', fontWeight: 400 }}>
                  公式 score = Σ 1/(k + rank)，k = {result.rrf_k}
                </Text>
              </Space>
            }
          >
            <Table
              rowKey={(r) => r.chunk_id}
              size="small"
              pagination={false}
              columns={fusedColumns}
              dataSource={result.fusion.items}
              locale={{ emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="无融合结果" /> }}
            />
          </Card>
        </>
      )}

      {!result && !loading && !err && (
        <Card style={{ borderRadius: 16 }}>
          <Empty description="输入问题后点击执行检索" />
        </Card>
      )}
    </div>
  )
}
