import { useCallback, useEffect, useRef, useState } from 'react'
import {
  Button,
  Card,
  Checkbox,
  Col,
  DatePicker,
  Drawer,
  Empty,
  Form,
  Input,
  List,
  message,
  Modal,
  Popconfirm,
  Row,
  Select,
  Space,
  Spin,
  Switch,
  Table,
  Tag,
  Tooltip,
  Typography,
  Upload,
} from 'antd'
import dayjs from 'dayjs'
import {
  DeleteOutlined,
  EyeOutlined,
  PlusOutlined,
  SearchOutlined,
  UploadOutlined,
} from '@ant-design/icons'
import {
  createKnowledgeBase,
  deleteDocument,
  deleteKnowledgeBase,
  fetchChunks,
  fetchKbAccessOptions,
  listDocuments,
  listKnowledgeBases,
  triggerVectorize,
  updateKnowledgeBase,
  uploadDocument,
} from '../api/kb'
import type { KbAccessOptions, UploadDocOptions } from '../api/kb'
import { getErrorMessage } from '../api/http'
import { SettingOutlined } from '@ant-design/icons'
import { formatTime } from '../utils/time'
import type { DocumentChunk, DocumentItem, DocStatus, KnowledgeBase } from '../types'

const STATUS_COLOR: Record<DocStatus, string> = {
  pending: 'default',
  processing: 'processing',
  completed: 'success',
  failed: 'error',
}

const STATUS_TEXT: Record<DocStatus, string> = {
  pending: '待向量化',
  processing: '向量化中',
  completed: '已完成',
  failed: '失败',
}

const FILE_TYPE_TEXT: Record<string, string> = {
  pdf: 'PDF',
  word: 'Word',
  markdown: 'Markdown',
  txt: 'TXT',
}

function formatSize(bytes?: number | null): string {
  if (!bytes) return '-'
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

function VisibilityFields({ accessOptions }: { accessOptions: KbAccessOptions }) {
  return (
    <>
      <Form.Item
        name="visibility"
        label="可见范围"
        initialValue="public"
        extra="受限知识库仅创建人、admin 与所选角色/用户可见，也不会进入其他人的检索范围"
      >
        <Select
          options={[
            { value: 'public', label: '公开：所有登录用户可见' },
            { value: 'restricted', label: '受限：仅指定角色或用户可见' },
          ]}
        />
      </Form.Item>
      <Form.Item noStyle shouldUpdate={(prev, cur) => prev.visibility !== cur.visibility}>
        {({ getFieldValue }) =>
          getFieldValue('visibility') === 'restricted' ? (
            <>
              <Form.Item
                name="allowed_roles"
                label="可见角色"
                dependencies={['allowed_users']}
                extra="只读取系统真实角色，不能手输；与指定用户同时生效时取并集"
                rules={[
                  ({ getFieldValue: get }) => ({
                    validator(_, value) {
                      if (value?.length || get('allowed_users')?.length) return Promise.resolve()
                      return Promise.reject(new Error('角色与指定用户至少选择一个'))
                    },
                  }),
                ]}
              >
                <Select
                  mode="multiple"
                  placeholder="选择角色"
                  options={accessOptions.roles.map((r) => ({ value: r, label: r }))}
                  notFoundContent="暂无角色"
                />
              </Form.Item>
              <Form.Item
                name="allowed_users"
                label="指定用户"
                dependencies={['allowed_roles']}
                extra={
                  accessOptions.can_grant_users
                    ? '按用户名或邮箱搜索，仅这些账号能访问该库'
                    : '指定用户需要管理员权限（user:manage），当前账号只能按角色授权'
                }
                rules={[
                  ({ getFieldValue: get }) => ({
                    validator(_, value) {
                      if (value?.length || get('allowed_roles')?.length) return Promise.resolve()
                      return Promise.reject(new Error('角色与指定用户至少选择一个'))
                    },
                  }),
                ]}
              >
                <Select
                  mode="multiple"
                  showSearch
                  optionFilterProp="label"
                  disabled={!accessOptions.can_grant_users}
                  placeholder="选择用户"
                  options={accessOptions.users.map((u) => ({
                    value: u.id,
                    label: `${u.username}（${u.email}）`,
                  }))}
                  notFoundContent="暂无用户"
                />
              </Form.Item>
            </>
          ) : null
        }
      </Form.Item>
    </>
  )
}

export default function KnowledgeBase() {
  const [kbs, setKbs] = useState<KnowledgeBase[]>([])
  const [selectedKbId, setSelectedKbId] = useState<string | null>(null)
  const [docs, setDocs] = useState<DocumentItem[]>([])
  const [loading, setLoading] = useState(false)
  const [search, setSearch] = useState('')
  const [activeOnly, setActiveOnly] = useState(false)
  const [versionModal, setVersionModal] = useState<{
    open: boolean
    file: File | null
    existing: DocumentItem | null
  }>({ open: false, file: null, existing: null })
  const [versionForm, setVersionForm] = useState({
    replace: true,
    version_no: '',
    valid_from: undefined as dayjs.Dayjs | undefined,
    valid_to: undefined as dayjs.Dayjs | undefined,
  })
  const [versionSubmitting, setVersionSubmitting] = useState(false)

  const [createOpen, setCreateOpen] = useState(false)
  const [createForm] = Form.useForm()
  const [editKb, setEditKb] = useState<KnowledgeBase | null>(null)
  const [editOpen, setEditOpen] = useState(false)
  const [editForm] = Form.useForm()
  const [editSubmitting, setEditSubmitting] = useState(false)
  const [accessOptions, setAccessOptions] = useState<KbAccessOptions>({
    roles: [],
    users: [],
    can_grant_users: false,
  })

  const [drawerOpen, setDrawerOpen] = useState(false)
  const [drawerDoc, setDrawerDoc] = useState<DocumentItem | null>(null)
  const [chunks, setChunks] = useState<DocumentChunk[]>([])
  const [chunksLoading, setChunksLoading] = useState(false)

  const pollRef = useRef<number | null>(null)

  const loadKbs = useCallback(async () => {
    try {
      const data = await listKnowledgeBases()
      setKbs(data)
      setSelectedKbId((prev) => prev && data.some((k) => k.id === prev) ? prev : (data[0]?.id ?? null))
    } catch (e) {
      message.error(getErrorMessage(e))
    }
  }, [])

  const loadDocs = useCallback(async (kbId: string, q?: string, active?: boolean) => {
    setLoading(true)
    try {
      const data = await listDocuments(kbId, q, active)
      setDocs(data)
    } catch (e) {
      message.error(getErrorMessage(e))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    loadKbs()
    fetchKbAccessOptions()
      .then(setAccessOptions)
      .catch(() => undefined)
  }, [loadKbs])

  useEffect(() => {
    if (selectedKbId) loadDocs(selectedKbId, search || undefined, activeOnly)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedKbId, activeOnly])

  const pollDocStatus = useCallback((docId: string) => {
    if (pollRef.current) window.clearInterval(pollRef.current)
    pollRef.current = window.setInterval(async () => {
      try {
        const all = await listDocuments(selectedKbId!)
        const target = all.find((d) => d.id === docId)
        if (target) setDocs((prev) => prev.map((d) => (d.id === docId ? target : d)))
        if (!target || target.status === 'completed' || target.status === 'failed') {
          if (pollRef.current) window.clearInterval(pollRef.current)
        }
      } catch {
        if (pollRef.current) window.clearInterval(pollRef.current)
      }
    }, 1500)
  }, [selectedKbId])

  useEffect(() => () => { if (pollRef.current) window.clearInterval(pollRef.current) }, [])

  const handleCreate = async () => {
    const values = await createForm.validateFields()
    try {
      await createKnowledgeBase({
        name: values.name,
        description: values.description,
        visibility: values.visibility ?? 'public',
        allowed_roles: values.visibility === 'restricted' ? values.allowed_roles ?? [] : [],
        allowed_users: values.visibility === 'restricted' ? values.allowed_users ?? [] : [],
      })
      message.success('知识库创建成功')
      setCreateOpen(false)
      createForm.resetFields()
      await loadKbs()
    } catch (e) {
      message.error(getErrorMessage(e))
    }
  }

  const openEdit = (kb: KnowledgeBase) => {
    setEditKb(kb)
    editForm.setFieldsValue({
      name: kb.name,
      description: kb.description ?? '',
      visibility: kb.visibility ?? 'public',
      allowed_roles: kb.allowed_roles ?? [],
      allowed_users: kb.allowed_users ?? [],
    })
    setEditOpen(true)
  }

  const handleEditOk = async () => {
    if (!editKb) return
    const values = await editForm.validateFields()
    setEditSubmitting(true)
    try {
      await updateKnowledgeBase(editKb.id, {
        name: values.name,
        description: values.description ?? '',
        visibility: values.visibility ?? 'public',
        allowed_roles: values.visibility === 'restricted' ? values.allowed_roles ?? [] : [],
        allowed_users: values.visibility === 'restricted' ? values.allowed_users ?? [] : [],
      })
      message.success('知识库设置已更新')
      setEditOpen(false)
      await loadKbs()
    } catch (e) {
      message.error(getErrorMessage(e))
    } finally {
      setEditSubmitting(false)
    }
  }

  const doUpload = async (file: File, opts?: UploadDocOptions) => {
    if (!selectedKbId) return
    try {
      const uploaded = await uploadDocument(selectedKbId, file, opts)
      message.success(`「${file.name}」上传成功，正在解析…`)
      loadDocs(selectedKbId, search || undefined, activeOnly)
      // 上传后直接建索引，不用再点一次「查看分块」才触发
      await triggerVectorize(uploaded.id)
      pollDocStatus(uploaded.id)
    } catch (e) {
      message.error(getErrorMessage(e))
    }
  }

  const handleUpload = async (file: File) => {
    if (!selectedKbId) return false
    const existing = docs.find(
      (d) => d.original_name === file.name && !d.superseded_by
    )
    if (existing) {
      setVersionModal({ open: true, file, existing })
      return false
    }
    await doUpload(file)
    return false
  }

  const handleVersionOk = async () => {
    if (versionSubmitting) return  // in-flight 防重：双击不产生第二次上传
    const { file, existing } = versionModal
    if (!file || !selectedKbId) {
      setVersionModal({ open: false, file: null, existing: null })
      return
    }
    const opts: UploadDocOptions = {
      version_no: versionForm.version_no || undefined,
      valid_from: versionForm.valid_from ? versionForm.valid_from.format('YYYY-MM-DD') : undefined,
      valid_to: versionForm.valid_to ? versionForm.valid_to.format('YYYY-MM-DD') : undefined,
      supersedes_doc_id: versionForm.replace && existing ? existing.id : undefined,
    }
    setVersionSubmitting(true)
    try {
      await doUpload(file, opts)
    } finally {
      setVersionSubmitting(false)
    }
    setVersionModal({ open: false, file: null, existing: null })
    setVersionForm({ replace: true, version_no: '', valid_from: undefined, valid_to: undefined })
  }

  const handleEye = async (doc: DocumentItem) => {
    setDrawerDoc(doc)
    setDrawerOpen(true)
    setChunksLoading(true)
    try {
      const data = await fetchChunks(doc.id)
      setChunks(data)
    } catch (e) {
      message.error(getErrorMessage(e))
    } finally {
      setChunksLoading(false)
    }
    if (doc.status === 'pending' || doc.status === 'failed') {
      try {
        await triggerVectorize(doc.id)
        message.info('已触发向量化，正在处理…')
        pollDocStatus(doc.id)
      } catch (e) {
        message.error(getErrorMessage(e))
      }
    }
  }

  const handleDeleteDoc = async (docId: string) => {
    try {
      await deleteDocument(docId)
      message.success('文档已删除')
      if (selectedKbId) loadDocs(selectedKbId, search || undefined, activeOnly)
    } catch (e) {
      message.error(getErrorMessage(e))
    }
  }

  const handleDeleteKb = async (kbId: string) => {
    try {
      await deleteKnowledgeBase(kbId)
      message.success('知识库已删除')
      await loadKbs()
    } catch (e) {
      message.error(getErrorMessage(e))
    }
  }

  const columns = [
    { title: '文档名称', dataIndex: 'original_name', key: 'name', ellipsis: true },
    {
      title: '格式',
      dataIndex: 'file_type',
      key: 'type',
      width: 90,
      render: (v: string) => FILE_TYPE_TEXT[v] ?? v.toUpperCase(),
    },
    { title: '大小', dataIndex: 'file_size', key: 'size', width: 90, render: (v: number | null) => formatSize(v) },
    {
      title: '状态', dataIndex: 'status', key: 'status', width: 90,
      render: (v: DocStatus) => <Tag color={STATUS_COLOR[v]}>{STATUS_TEXT[v]}</Tag>,
    },
    {
      title: '效力', key: 'governance', width: 60,
      render: (_: unknown, doc: DocumentItem) => (
        <Space direction="vertical" size={2}>
          {doc.superseded_by
            ? <Tag color="red">已废止</Tag>
            : <Tag color="green">现行</Tag>}
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            {doc.version_no ? `${doc.version_no} · ` : ''}
            {doc.valid_from || doc.valid_to
              ? `${doc.valid_from ?? '…'} ~ ${doc.valid_to ?? '…'}`
              : '长期有效'}
          </Typography.Text>
        </Space>
      ),
    },
    { title: '上传时间', dataIndex: 'created_at', key: 'time', width: 140, render: (v: string) => formatTime(v) },
    {
      title: '操作', key: 'action', width: 100,
      render: (_: unknown, doc: DocumentItem) => (
        <Space>
          <Button
            type="text" size="small" icon={<EyeOutlined />}
            loading={doc.status === 'processing'}
            onClick={() => handleEye(doc)}
          />
          <Popconfirm title="确认删除该文档？" onConfirm={() => handleDeleteDoc(doc.id)}>
            <Button type="text" danger size="small" icon={<DeleteOutlined />} />
          </Popconfirm>
        </Space>
      ),
    },
  ]

  const selectedKb = kbs.find((k) => k.id === selectedKbId)

  return (
    <Row gutter={16}>
      <Col flex="0 0 300px">
        <Card
          title="知识库"
          size="small"
          extra={
            <Button type="primary" size="small" icon={<PlusOutlined />} onClick={() => setCreateOpen(true)}>
              新建
            </Button>
          }
        >
          <List
            dataSource={kbs}
            style={{ maxHeight: '70vh', overflow: 'auto', paddingRight: 4 }}
            locale={{ emptyText: <Empty description="暂无知识库" /> }}
            renderItem={(kb) => {
              const active = kb.id === selectedKbId
              return (
                <div
                  onClick={() => setSelectedKbId(kb.id)}
                  style={{
                    cursor: 'pointer',
                    borderRadius: 10,
                    padding: '10px 10px 10px 12px',
                    marginBottom: 8,
                    display: 'flex',
                    alignItems: 'center',
                    gap: 6,
                    background: active ? '#eef2ff' : '#fafafa',
                    border: active ? '1px solid #c7d2fe' : '1px solid #f0f0f0',
                    boxShadow: active ? '0 2px 8px rgba(79,70,229,.12)' : 'none',
                    transition: 'all .15s ease',
                  }}
                >
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <Tooltip title={kb.name} placement="right">
                      <Typography.Text
                        strong
                        style={{
                          display: 'block',
                          fontSize: 14,
                          lineHeight: '20px',
                          whiteSpace: 'nowrap',
                          overflow: 'hidden',
                          textOverflow: 'ellipsis',
                        }}
                      >
                        {kb.name}
                      </Typography.Text>
                    </Tooltip>
                    <div style={{ marginTop: 6, display: 'flex', alignItems: 'center', gap: 6 }}>
                      {kb.visibility === 'restricted'
                        ? <Tag color="orange" style={{ marginInlineEnd: 0 }}>受限</Tag>
                        : <Tag color="blue" style={{ marginInlineEnd: 0 }}>公开</Tag>}
                      {kb.description ? (
                        <Typography.Text
                          type="secondary"
                          ellipsis
                          style={{ fontSize: 12, flex: 1, minWidth: 0 }}
                        >
                          {kb.description}
                        </Typography.Text>
                      ) : null}
                    </div>
                  </div>
                  <Space size={0} onClick={(e) => e.stopPropagation()}>
                    <Button
                      type="text"
                      size="small"
                      icon={<SettingOutlined />}
                      onClick={() => openEdit(kb)}
                    />
                    <Popconfirm
                      title="删除知识库将同时删除其下所有文档"
                      onConfirm={() => handleDeleteKb(kb.id)}
                    >
                      <Button type="text" size="small" danger icon={<DeleteOutlined />} />
                    </Popconfirm>
                  </Space>
                </div>
              )
            }}
          />
        </Card>
      </Col>
      <Col flex="1 1 0" style={{ minWidth: 0 }}>
        <Card
          title={selectedKb?.name ?? '选择知识库'}
          extra={
            <Space>
              <Space>
                <Switch
                  size="small"
                  checked={activeOnly}
                  onChange={setActiveOnly}
                />
                <Typography.Text type="secondary">只看现行</Typography.Text>
              </Space>
              <Input
                allowClear
                placeholder="搜索文档名"
                prefix={<SearchOutlined />}
                style={{ width: 180 }}
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                onPressEnter={() => selectedKbId && loadDocs(selectedKbId, search || undefined, activeOnly)}
              />
              <Upload showUploadList={false} beforeUpload={handleUpload} accept=".pdf,.docx,.md,.txt">
                <Button type="primary" icon={<UploadOutlined />} disabled={!selectedKbId}>
                  上传文档
                </Button>
              </Upload>
            </Space>
          }
        >
          <Table
            rowKey="id"
            loading={loading}
            dataSource={docs}
            columns={columns}
            pagination={false}
            locale={{ emptyText: <Empty description="暂无文档，点击右上角上传" /> }}
          />
        </Card>
      </Col>

      <Modal
        title="新建知识库"
        open={createOpen}
        onOk={handleCreate}
        onCancel={() => setCreateOpen(false)}
        okText="创建"
      >
        <Form form={createForm} layout="vertical" style={{ marginTop: 12 }}>
          <Form.Item name="name" label="名称" rules={[{ required: true, message: '请输入名称' }]}>
            <Input placeholder="如：学生手册与教务制度知识库" />
          </Form.Item>
          <Form.Item name="description" label="描述">
            <Input.TextArea rows={2} placeholder="可选" />
          </Form.Item>
          <VisibilityFields accessOptions={accessOptions} />
        </Form>
      </Modal>

      <Modal
        title={editKb ? `知识库设置 · ${editKb.name}` : '知识库设置'}
        open={editOpen}
        onOk={handleEditOk}
        onCancel={() => setEditOpen(false)}
        okText="保存"
        confirmLoading={editSubmitting}
        destroyOnClose
      >
        <Form form={editForm} layout="vertical" style={{ marginTop: 12 }}>
          <Form.Item name="name" label="名称" rules={[{ required: true, message: '请输入名称' }]}>
            <Input />
          </Form.Item>
          <Form.Item name="description" label="描述">
            <Input.TextArea rows={2} placeholder="可选" />
          </Form.Item>
          <VisibilityFields accessOptions={accessOptions} />
        </Form>
      </Modal>

      <Drawer
        title={drawerDoc ? `分块预览 · ${drawerDoc.original_name}` : '分块预览'}
        width={520}
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
      >
        {drawerDoc && (
          <Typography.Text type="secondary">
            状态：{STATUS_TEXT[drawerDoc.status]}，共 {chunks.length} 个分块
          </Typography.Text>
        )}
        <Spin spinning={chunksLoading} style={{ marginTop: 12 }}>
          <List
            dataSource={chunks}
            renderItem={(c, i) => (
              <List.Item key={i} style={{ display: 'block', borderBottom: '1px dashed #eee', padding: '12px 0' }}>
                <Typography.Text strong>
                  分块 #{c.chunk_index}
                  {c.title ? <Tag style={{ marginLeft: 8 }} color="blue">{c.title}</Tag> : null}
                </Typography.Text>
                <Typography.Paragraph style={{ marginTop: 4, marginBottom: 0 }} ellipsis={{ rows: 4, expandable: true }}>
                  {c.content}
                </Typography.Paragraph>
              </List.Item>
            )}
          />
        </Spin>
      </Drawer>

      <Modal
        title={`检测到同名文档：${versionModal.existing?.original_name ?? ''}`}
        open={versionModal.open}
        onOk={handleVersionOk}
        onCancel={() => setVersionModal({ open: false, file: null, existing: null })}
        okText="上传"
        confirmLoading={versionSubmitting}
      >
        <Form layout="vertical" style={{ marginTop: 12 }}>
          <Form.Item>
            <Typography.Paragraph type="secondary">
              知识库中已有同名且现行的文档。勾选替换后，新文档向量化成功时旧版将自动废止并清除其检索分块。
            </Typography.Paragraph>
          </Form.Item>
          <Form.Item label="版本信息">
            <Checkbox
              checked={versionForm.replace}
              onChange={(e) => setVersionForm((f) => ({ ...f, replace: e.target.checked }))}
            >
              作为新版本替换旧文档
            </Checkbox>
          </Form.Item>
          <Form.Item label="版本号">
            <Input
              placeholder="如：2024 版"
              value={versionForm.version_no}
              onChange={(e) => setVersionForm((f) => ({ ...f, version_no: e.target.value }))}
            />
          </Form.Item>
          <Form.Item label="生效 / 失效日期（可选）">
            <Space.Compact block>
              <DatePicker
                style={{ width: '50%' }}
                value={versionForm.valid_from}
                onChange={(v) => setVersionForm((f) => ({ ...f, valid_from: v ?? undefined }))}
              />
              <DatePicker
                style={{ width: '50%' }}
                value={versionForm.valid_to}
                onChange={(v) => setVersionForm((f) => ({ ...f, valid_to: v ?? undefined }))}
              />
            </Space.Compact>
          </Form.Item>
        </Form>
      </Modal>
    </Row>
  )
}
