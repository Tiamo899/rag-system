import { useEffect, useState } from 'react'
import { Alert, Card, Descriptions, Space, Spin, Tag, Typography, message } from 'antd'
import { listSystemConfigs } from '../api/admin'
import { getErrorMessage } from '../api/http'
import type { SystemConfig } from '../types'

const GROUPS: { title: string; keys: string[] }[] = [
  { title: '大模型', keys: ['llm.provider', 'llm.api_key', 'llm.base_url', 'llm.model'] },
  {
    title: '向量模型',
    keys: [
      'embedding.provider',
      'embedding.api_key',
      'embedding.base_url',
      'embedding.model',
      'embedding.dim',
    ],
  },
  { title: '检索', keys: ['relevance.threshold'] },
  { title: '分块参数', keys: ['chunk.size', 'chunk.overlap'] },
]

const LABELS: Record<string, string> = {
  'llm.provider': '供应商',
  'llm.api_key': 'API Key',
  'llm.base_url': 'API 地址',
  'llm.model': '模型名称',
  'embedding.provider': '供应商',
  'embedding.api_key': 'API Key',
  'embedding.base_url': 'API 地址',
  'embedding.model': '模型名称',
  'embedding.dim': '向量维度',
  'relevance.threshold': '相关度阈值',
  'chunk.size': '默认分块大小',
  'chunk.overlap': '默认分块重叠',
}

const ENV_HINTS = [
  'LLM_PROVIDER=openai',
  'LLM_API_KEY=sk-...',
  'LLM_BASE_URL=https://api.siliconflow.cn/v1',
  'LLM_MODEL=Qwen/Qwen2.5-7B-Instruct',
  'EMBEDDING_MODEL=BAAI/bge-m3',
  'EMBEDDING_DIM=1024',
  'RELEVANCE_THRESHOLD=0.02',
]

export default function AdminSettings() {
  const [configs, setConfigs] = useState<Record<string, SystemConfig>>({})
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    setLoading(true)
    listSystemConfigs()
      .then((data) => setConfigs(Object.fromEntries(data.map((c) => [c.key, c]))))
      .catch((e) => message.error(getErrorMessage(e)))
      .finally(() => setLoading(false))
  }, [])

  if (loading) {
    return (
      <div style={{ textAlign: 'center', padding: 48 }}>
        <Spin />
      </div>
    )
  }

  return (
    <div>
      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 16 }}
        message={
          <div>
            以下为<strong>当前生效配置</strong>，读取自 <Typography.Text code>backend/.env</Typography.Text>，此处
            不可修改。
            <br />
            修改请编辑 <Typography.Text code>backend/.env</Typography.Text> 中对应变量，然后重启后端容器生效。
          </div>
        }
      />

      {GROUPS.map((g) => {
        const items = g.keys
          .filter((k) => configs[k])
          .map((k) => {
            const c = configs[k]
            const notConfigured = c.value === '（未配置）'
            return {
              key: k,
              label: (
                <Space size={6} wrap>
                  <span>{LABELS[k] ?? k}</span>
                  {c.env_key ? <Tag style={{ fontSize: 11 }}>{c.env_key}</Tag> : null}
                </Space>
              ),
              children: (
                <Typography.Text type={notConfigured ? 'secondary' : undefined} code>
                  {notConfigured ? '未配置（使用默认）' : c.value}
                </Typography.Text>
              ),
            }
          })
        return (
          <Card key={g.title} size="small" title={g.title} style={{ marginBottom: 12 }}>
            <Descriptions size="small" column={1} items={items} />
          </Card>
        )
      })}

      <Card size="small" title="在哪里改？" style={{ marginBottom: 12 }}>
        <Typography.Paragraph type="secondary" style={{ marginBottom: 8 }}>
          以上配置均在 <Typography.Text code>backend/.env</Typography.Text> 中定义，编辑后需重启后端：
        </Typography.Paragraph>
        <Typography.Paragraph style={{ marginBottom: 0 }}>
          <pre style={{ margin: 0, padding: 8, background: '#f5f5f5', borderRadius: 6 }}>
{ENV_HINTS.join('\n')}
          </pre>
        </Typography.Paragraph>
        <Typography.Paragraph type="secondary" style={{ marginTop: 8, marginBottom: 0, fontSize: 12 }}>
          其中 <Typography.Text code>chunk.size</Typography.Text> /{' '}
          <Typography.Text code>chunk.overlap</Typography.Text> 为新建知识库默认值，创建知识库时可在表单中单独设置。
        </Typography.Paragraph>
      </Card>
    </div>
  )
}
