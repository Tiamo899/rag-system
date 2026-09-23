import { useEffect, useRef, useState } from 'react'
import {
  Button,
  Card,
  Checkbox,
  Col,
  Empty,
  Input,
  List,
  message,
  Modal,
  Popconfirm,
  Row,
  Select,
  Space,
  Spin,
  Tag,
  Typography,
} from 'antd'
import {
  DeleteOutlined,
  DislikeOutlined,
  LikeOutlined,
  PlusOutlined,
  RobotOutlined,
  UserOutlined,
} from '@ant-design/icons'
import ReactMarkdown from 'react-markdown'
import {
  createSession,
  deleteSession,
  getSessionDetail,
  listSessions,
  sendFeedback,
  updateSession,
} from '../api/chat'
import { listKnowledgeBases } from '../api/kb'
import { getErrorMessage } from '../api/http'
import { streamSSE } from '../utils/sse'
import type { ChatMessage, ChatSession, KnowledgeBase, Source } from '../types'

const QUICK_PROMPTS = [
  '挂科了还能申请奖学金吗？',
  '想转专业需要满足什么条件？',
  '每学期最少要选多少学分？',
  '国家助学金什么时候申请？',
]

interface Bubble {
  role: 'user' | 'assistant'
  content: string
  sources: Source[]
  id?: string
  feedback?: 'like' | 'dislike' | null
}

export default function Chat() {
  const [sessions, setSessions] = useState<ChatSession[]>([])
  const [current, setCurrent] = useState<ChatSession | null>(null)
  const [messages, setMessages] = useState<Bubble[]>([])
  const [input, setInput] = useState('')
  const [sending, setSending] = useState(false)
  const [streaming, setStreaming] = useState('')
  const [phase, setPhase] = useState<'idle' | 'retrieving' | 'thinking' | 'generating'>('idle')
  const [kbs, setKbs] = useState<KnowledgeBase[]>([])
  const [kbId, setKbId] = useState<string | undefined>(undefined)
  const [sourceModal, setSourceModal] = useState<Source | null>(null)
  const [loadingDetail, setLoadingDetail] = useState(false)
  const [multiSelect, setMultiSelect] = useState(false)
  const [selectedSessions, setSelectedSessions] = useState<string[]>([])

  const scrollRef = useRef<HTMLDivElement>(null)
  const abortRef = useRef<AbortController | null>(null)

  useEffect(() => {
    listSessions().then(setSessions).catch((e) => message.error(getErrorMessage(e)))
    listKnowledgeBases()
      .then((data) => setKbs(data))
      .catch(() => undefined)
    // kbId 保持 undefined = 默认「全部知识库」；用户可在标题栏下拉切换
  }, [])

  useEffect(() => {
    if (scrollRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight
  }, [messages, streaming])

  useEffect(() => () => abortRef.current?.abort(), [])

  const openSession = async (sid: string) => {
    setLoadingDetail(true)
    try {
      const detail = await getSessionDetail(sid)
      setCurrent(detail.session)
      setPhase('idle')
      setMessages(
        detail.messages
          .filter((m) => m.role !== 'system')
          .map((m) => ({
            role: m.role as Bubble['role'],
            content: m.content,
            sources: m.sources,
            id: m.id,
            feedback: m.feedback ?? null,
          }))
      )
    } catch (e) {
      message.error(getErrorMessage(e))
    } finally {
      setLoadingDetail(false)
    }
  }

  const handleNewSession = async () => {
    const s = await createSession({ title: '新对话', kb_id: kbId })
    setSessions((prev) => [s, ...prev])
    setCurrent(s)
    setMessages([])
    setStreaming('')
    setPhase('idle')
  }

  const handleDeleteSession = async (sid: string) => {
    await deleteSession(sid)
    setSessions((prev) => prev.filter((s) => s.id !== sid))
    if (current?.id === sid) {
      setCurrent(null)
      setMessages([])
    }
  }

  const toggleSelectAll = () => {
    setSelectedSessions(
      selectedSessions.length === sessions.length ? [] : sessions.map((s) => s.id)
    )
  }

  const toggleSelect = (id: string) => {
    setSelectedSessions((prev) =>
      prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]
    )
  }

  const handleBatchDeleteSessions = async () => {
    if (!selectedSessions.length) return
    try {
      for (const sid of selectedSessions) await deleteSession(sid)
      setSessions((prev) => prev.filter((s) => !selectedSessions.includes(s.id)))
      if (current && selectedSessions.includes(current.id)) {
        setCurrent(null)
        setMessages([])
      }
      message.success(`已删除 ${selectedSessions.length} 个会话`)
      setSelectedSessions([])
      setMultiSelect(false)
    } catch (e) {
      message.error(getErrorMessage(e))
    }
  }

  const handleFeedback = async (msg: Bubble, fb: 'like' | 'dislike') => {
    if (!msg.id) return
    const next = msg.feedback === fb ? null : fb
    const prev = msg.feedback
    setMessages((prevList) =>
      prevList.map((m) => (m.id === msg.id ? { ...m, feedback: next } : m))
    )
    try {
      await sendFeedback(msg.id, next)
    } catch (e) {
      message.error(getErrorMessage(e))
      setMessages((prevList) =>
        prevList.map((m) => (m.id === msg.id ? { ...m, feedback: prev } : m))
      )
    }
  }

  const send = async (textArg?: string) => {
    const text = (textArg ?? input).trim()
    if (!text || sending) return
    setInput('')
    let sid = current?.id
    if (!sid) {
      const s = await createSession({ title: text.slice(0, 20), kb_id: kbId })
      setSessions((prev) => [s, ...prev])
      setCurrent(s)
      sid = s.id
    } else if (current?.title === '新对话') {
      // 已有会话但标题还是默认值：用问题摘要更新会话标题
      updateSession(sid, { title: text.slice(0, 20) })
        .then((s) => {
          setSessions((prev) => prev.map((x) => (x.id === s.id ? s : x)))
          setCurrent(s)
        })
        .catch(() => undefined)
    }
    setMessages((prev) => [...prev, { role: 'user', content: text, sources: [] }])
    setSending(true)
    setStreaming('')
    setPhase('retrieving')

    const token = localStorage.getItem('access_token') ?? ''
    const controller = new AbortController()
    abortRef.current = controller
    try {
      await streamSSE(
        `/api/v1/chat/sessions/${sid}/messages`,
        { content: text, kb_id: kbId },
        token,
        (frame) => {
          if (frame.event === 'status') {
            const d = frame.data as { stage: string }
            setPhase(d.stage === 'thinking' ? 'thinking' : 'retrieving')
          } else if (frame.event === 'token') {
            const d = frame.data as { text: string }
            setPhase('generating')
            setStreaming((prev) => prev + d.text)
          } else if (frame.event === 'done') {
            const d = frame.data as { message_id: string; answer: string; sources: Source[] }
            setMessages((prev) => [
              ...prev,
              { role: 'assistant', content: d.answer, sources: d.sources, id: d.message_id, feedback: null },
            ])
            setStreaming('')
            setPhase('idle')
            setSending(false)
          } else if (frame.event === 'error') {
            const d = frame.data as { message: string }
            message.error(d.message || '生成失败')
            setStreaming('')
            setPhase('idle')
            setSending(false)
          }
        },
        controller.signal,
      )
    } catch (e) {
      message.error(getErrorMessage(e))
      setStreaming('')
      setSending(false)
    }
  }

  const bubbleStyle: Record<Bubble['role'], React.CSSProperties> = {
    user: { padding: '10px 14px', maxWidth: '72%', marginLeft: 'auto' },
    assistant: { padding: '12px 16px', maxWidth: '84%' },
  }

  return (
    <Row gutter={16} style={{ height: 'calc(100vh - 150px)' }}>
      <Col span={5}>
        <Card
          title="会话"
          size="small"
          extra={
            <Space>
              {multiSelect ? (
                <Button
                  size="small"
                  onClick={() => {
                    setMultiSelect(false)
                    setSelectedSessions([])
                  }}
                >
                  退出
                </Button>
              ) : (
                <Button size="small" onClick={() => setMultiSelect(true)}>
                  多选
                </Button>
              )}
              <Button type="primary" size="small" icon={<PlusOutlined />} onClick={handleNewSession}>
                新建
              </Button>
            </Space>
          }
          bodyStyle={{ padding: 0 }}
        >
          {multiSelect && (
            <div
              style={{
                padding: '8px 12px',
                display: 'flex',
                alignItems: 'center',
                gap: 8,
                borderBottom: '1px solid #f0f0f0',
              }}
            >
              <Checkbox
                checked={selectedSessions.length === sessions.length && sessions.length > 0}
                indeterminate={
                  selectedSessions.length > 0 && selectedSessions.length < sessions.length
                }
                onChange={toggleSelectAll}
              />
              <span style={{ fontSize: 12 }}>已选 {selectedSessions.length} 项</span>
              <Button
                size="small"
                danger
                disabled={!selectedSessions.length}
                onClick={handleBatchDeleteSessions}
              >
                批量删除
              </Button>
            </div>
          )}
          <List
            dataSource={sessions}
            style={{ maxHeight: multiSelect ? '66vh' : '72vh', overflow: 'auto' }}
            locale={{ emptyText: <Empty description="暂无会话" /> }}
            renderItem={(s) => (
              <List.Item
                className={`chat-session-item${
                  !multiSelect && s.id === current?.id ? ' active' : ''
                }`}
                onClick={() => (multiSelect ? toggleSelect(s.id) : openSession(s.id))}
                style={{
                  cursor: 'pointer',
                  padding: '10px 12px',
                  background: multiSelect && selectedSessions.includes(s.id) ? '#eef2ff' : undefined,
                }}
                actions={
                  multiSelect
                    ? []
                    : [
                        <Popconfirm
                          key="del"
                          title="删除该会话？"
                          onConfirm={() => handleDeleteSession(s.id)}
                        >
                          <Button
                            type="text"
                            size="small"
                            danger
                            icon={<DeleteOutlined />}
                            onClick={(e) => e.stopPropagation()}
                          />
                        </Popconfirm>,
                      ]
                }
              >
                {multiSelect && (
                  <Checkbox
                    checked={selectedSessions.includes(s.id)}
                    onClick={(e) => e.stopPropagation()}
                    onChange={() => toggleSelect(s.id)}
                  />
                )}
                <span style={{ marginLeft: multiSelect ? 8 : 0 }}>{s.title || '新对话'}</span>
              </List.Item>
            )}
          />
        </Card>
      </Col>
      <Col span={19}>
        <Card
          size="small"
          style={{ height: '100%', display: 'flex', flexDirection: 'column' }}
          bodyStyle={{ flex: 1, display: 'flex', flexDirection: 'column', padding: 12 }}
          title={
            <Space>
              <span>{current?.title ?? '智能问答'}</span>
              <Select
                style={{ width: 180 }}
                size="small"
                value={kbId ?? 'all'}
                placeholder="选择知识库"
                onChange={(v) => setKbId(v === 'all' ? undefined : v)}
                options={[{ label: '全部知识库', value: 'all' }, ...kbs.map((k) => ({ label: k.name, value: k.id }))]}
              />
            </Space>
          }
        >
          <div ref={scrollRef} style={{ flex: 1, overflow: 'auto', marginBottom: 12 }}>
            <Spin spinning={loadingDetail}>
              {messages.length === 0 && !streaming ? (
                <div style={{ marginTop: 48, textAlign: 'center', padding: '0 24px' }}>
                  <div
                    className="avatar-assistant"
                    style={{
                      width: 60,
                      height: 60,
                      borderRadius: 18,
                      display: 'inline-flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      fontSize: 30,
                      color: '#fff',
                      marginBottom: 18,
                    }}
                  >
                    <RobotOutlined />
                  </div>
                  <Typography.Title level={5} style={{ marginBottom: 6, fontWeight: 700 }}>
                    你好，我是教务智能问答助手
                  </Typography.Title>
                  <Typography.Paragraph type="secondary" style={{ marginBottom: 24 }}>
                    选择一个常见问题，或直接在下方输入，答案将标注引用来源
                  </Typography.Paragraph>
                  <Space
                    wrap
                    size={[10, 10]}
                    style={{ maxWidth: 600, justifyContent: 'center' }}
                  >
                    {QUICK_PROMPTS.map((p) => (
                      <Button key={p} size="large" className="quick-chip" onClick={() => send(p)}>
                        {p}
                      </Button>
                    ))}
                  </Space>
                </div>
              ) : (
                <Space direction="vertical" size={12} style={{ width: '100%' }}>
                  {messages.map((m, i) => (
                    <div
                      key={i}
                      style={{
                        display: 'flex',
                        gap: 10,
                        flexDirection: m.role === 'user' ? 'row-reverse' : 'row',
                      }}
                    >
                      <span
                        className={m.role === 'user' ? 'avatar-user' : 'avatar-assistant'}
                        style={{
                          width: 32,
                          height: 32,
                          borderRadius: 10,
                          display: 'inline-flex',
                          alignItems: 'center',
                          justifyContent: 'center',
                          fontSize: 16,
                          color: '#fff',
                          flexShrink: 0,
                          marginTop: 2,
                        }}
                      >
                        {m.role === 'user' ? <UserOutlined /> : <RobotOutlined />}
                      </span>
                      <div
                        className={m.role === 'user' ? 'bubble-user' : 'bubble-assistant'}
                        style={{ ...bubbleStyle[m.role], flex: m.role === 'assistant' ? 1 : undefined }}
                      >
                        {m.role === 'assistant' ? <ReactMarkdown>{m.content}</ReactMarkdown> : m.content}
                        {m.role === 'assistant' && m.sources.length > 0 && (
                          <div style={{ marginTop: 10 }}>
                            <Typography.Text type="secondary" style={{ fontSize: 12 }}>引用来源：</Typography.Text>
                            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginTop: 2 }}>
                              {m.sources.map((s, idx) => (
                                <Tag
                                  key={idx}
                                  className="source-tag"
                                  style={{ cursor: 'pointer', marginInlineEnd: 0 }}
                                  onClick={() => setSourceModal(s)}
                                >
                                  [{idx + 1}] {s.title ?? s.doc_name ?? '来源'}
                                </Tag>
                              ))}
                            </div>
                          </div>
                        )}
                        {m.role === 'assistant' && (
                          <Space size={2} style={{ marginTop: 2 }}>
                            <Button
                              type="text"
                              size="small"
                              icon={<LikeOutlined />}
                              style={{ color: m.feedback === 'like' ? '#6366f1' : 'rgba(0,0,0,0.45)' }}
                              onClick={() => handleFeedback(m, 'like')}
                            />
                            <Button
                              type="text"
                              size="small"
                              icon={<DislikeOutlined />}
                              style={{ color: m.feedback === 'dislike' ? '#f5222d' : 'rgba(0,0,0,0.45)' }}
                              onClick={() => handleFeedback(m, 'dislike')}
                            />
                          </Space>
                        )}
                      </div>
                    </div>
                  ))}
                  {(streaming || phase !== 'idle') && (
                    <div style={{ display: 'flex', gap: 10 }}>
                      <span
                        className="avatar-assistant"
                        style={{
                          width: 32,
                          height: 32,
                          borderRadius: 10,
                          display: 'inline-flex',
                          alignItems: 'center',
                          justifyContent: 'center',
                          fontSize: 16,
                          color: '#fff',
                          flexShrink: 0,
                          marginTop: 2,
                        }}
                      >
                        <RobotOutlined />
                      </span>
                      <div className="bubble-assistant" style={bubbleStyle.assistant}>
                        {streaming ? (
                          <>
                            <ReactMarkdown>{streaming}</ReactMarkdown>
                            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                              <span className="typing-dot" />
                              <span className="typing-dot" />
                              <span className="typing-dot" />
                            </Typography.Text>
                          </>
                        ) : (
                          <Typography.Text type="secondary" style={{ fontSize: 13 }}>
                            {phase === 'thinking' ? '正在思考…' : '正在检索知识库…'}
                          </Typography.Text>
                        )}
                      </div>
                    </div>
                  )}
                </Space>
              )}
            </Spin>
          </div>
          <div
            style={{
              display: 'flex',
              gap: 10,
              alignItems: 'flex-end',
              padding: 10,
              border: '1px solid #e9ecf5',
              borderRadius: 14,
              background: '#fbfcfe',
              boxShadow: '0 4px 16px -10px rgba(16,24,40,0.18)',
            }}
          >
            <Input.TextArea
              rows={2}
              bordered={false}
              placeholder="输入问题，Enter 发送，Shift+Enter 换行"
              value={input}
              disabled={sending}
              style={{ background: 'transparent', resize: 'none', padding: '4px 6px' }}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                  e.preventDefault()
                  send()
                }
              }}
            />
            <Button
              type="primary"
              loading={sending}
              onClick={() => send()}
              style={{ height: 42, paddingInline: 22, borderRadius: 11, flexShrink: 0 }}
            >
              发送
            </Button>
          </div>
        </Card>
      </Col>

      <Modal
        open={!!sourceModal}
        title={
          sourceModal?.title
            ? `《${sourceModal.title}》${sourceModal?.doc_name ? ` · ${sourceModal.doc_name}` : ''}`
            : `引用来源${sourceModal?.doc_name ? ` · ${sourceModal.doc_name}` : ''}`
        }
        footer={null}
        onCancel={() => setSourceModal(null)}
        width={600}
      >
        {sourceModal && (
          <>
            <Typography.Paragraph type="secondary" style={{ fontSize: 12 }}>
              相似度：{(sourceModal.score * 100).toFixed(1)}% · 分块 #{sourceModal.chunk_index ?? '-'}
            </Typography.Paragraph>
            <Typography.Paragraph style={{ whiteSpace: 'pre-wrap' }}>
              {sourceModal.content}
            </Typography.Paragraph>
          </>
        )}
      </Modal>
    </Row>
  )
}
