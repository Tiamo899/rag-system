import { useCallback, useEffect, useState } from 'react'
import type { Key } from 'react'
import {
  Button,
  Form,
  Input,
  Modal,
  Popconfirm,
  Select,
  Space,
  Switch,
  Table,
  Tag,
  message,
} from 'antd'
import { DeleteOutlined, EditOutlined, PlusOutlined } from '@ant-design/icons'
import { createUser, deleteUser, listRoles, listUsers, updateUser } from '../api/admin'
import { getErrorMessage } from '../api/http'
import { useAuthStore } from '../store/auth'
import { formatTime } from '../utils/time'
import type { Role, User } from '../types'

const PAGE_SIZE = 10

export default function AdminUsers() {
  const me = useAuthStore((s) => s.user)
  const [users, setUsers] = useState<User[]>([])
  const [roles, setRoles] = useState<Role[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [search, setSearch] = useState('')
  const [loading, setLoading] = useState(false)
  const [modalOpen, setModalOpen] = useState(false)
  const [editing, setEditing] = useState<User | null>(null)
  const [saving, setSaving] = useState(false)
  const [selectedKeys, setSelectedKeys] = useState<Key[]>([])
  const [form] = Form.useForm()

  const load = useCallback(async (targetPage = page, keyword = search) => {
    setLoading(true)
    try {
      const data = await listUsers({
        page: targetPage,
        page_size: PAGE_SIZE,
        search: keyword || undefined,
      })
      setUsers(data.items)
      setTotal(data.total)
    } catch (e) {
      message.error(getErrorMessage(e))
    } finally {
      setLoading(false)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [page, search])

  useEffect(() => {
    load()
  }, [load])

  useEffect(() => {
    listRoles().then(setRoles).catch((e) => message.error(getErrorMessage(e)))
  }, [])

  const openCreate = () => {
    setEditing(null)
    form.resetFields()
    form.setFieldsValue({ role_ids: [], status: 1 })
    setModalOpen(true)
  }

  const openEdit = (user: User) => {
    setEditing(user)
    form.setFieldsValue({
      username: user.username,
      email: user.email,
      role_ids: user.role_ids,
      status: user.status,
    })
    setModalOpen(true)
  }

  const handleSubmit = async () => {
    const values = await form.validateFields()
    setSaving(true)
    try {
      if (editing) {
        const payload: Record<string, unknown> = {
          username: values.username,
          email: values.email,
          role_ids: values.role_ids,
          status: values.status ? 1 : 0,
        }
        if (values.password) payload.password = values.password
        await updateUser(editing.id, payload)
        message.success('已保存')
      } else {
        await createUser({
          username: values.username,
          email: values.email,
          password: values.password,
          role_ids: values.role_ids,
          status: values.status ? 1 : 0,
        })
        message.success('已创建')
      }
      setModalOpen(false)
      load(page)
    } catch (e) {
      message.error(getErrorMessage(e))
    } finally {
      setSaving(false)
    }
  }

  const toggleStatus = async (user: User) => {
    try {
      await updateUser(user.id, { status: user.status === 1 ? 0 : 1 })
      message.success('状态已更新')
      load(page)
    } catch (e) {
      message.error(getErrorMessage(e))
    }
  }

  const batchSetStatus = async (status: number) => {
    if (!selectedKeys.length) return
    const targets = users.filter((u) => selectedKeys.includes(u.id))
    const protectedOnes = targets.filter((u) => isSelf(u) || isAdminUser(u))
    const valid = targets.filter((u) => !protectedOnes.includes(u))
    try {
      for (const u of valid) await updateUser(u.id, { status })
      message.success(
        protectedOnes.length
          ? `已${status ? '启用' : '禁用'} ${valid.length} 个，${protectedOnes.length} 个受保护跳过`
          : `已${status ? '启用' : '禁用'} ${valid.length} 个用户`
      )
      setSelectedKeys([])
      load(page)
    } catch (e) {
      message.error(getErrorMessage(e))
    }
  }

  const batchDelete = async () => {
    if (!selectedKeys.length) return
    const targets = users.filter((u) => selectedKeys.includes(u.id))
    const protectedOnes = targets.filter((u) => isSelf(u) || isAdminUser(u))
    const valid = targets.filter((u) => !protectedOnes.includes(u))
    try {
      for (const u of valid) await deleteUser(u.id)
      message.success(
        protectedOnes.length
          ? `已删除 ${valid.length} 个，${protectedOnes.length} 个受保护跳过`
          : `已删除 ${valid.length} 个用户`
      )
      setSelectedKeys([])
      load(page)
    } catch (e) {
      message.error(getErrorMessage(e))
    }
  }

  const handleDelete = async (user: User) => {
    try {
      await deleteUser(user.id)
      message.success('已删除')
      load(page)
    } catch (e) {
      message.error(getErrorMessage(e))
    }
  }

  const roleOptions = roles.map((r) => ({ label: r.name, value: r.id }))
  const isSelf = (u: User) => u.id === me?.id
  const isAdminUser = (u: User) => u.roles.includes('admin')

  const columns = [
    { title: '用户名', dataIndex: 'username', key: 'username' },
    { title: '邮箱', dataIndex: 'email', key: 'email', ellipsis: true },
    {
      title: '角色',
      dataIndex: 'roles',
      key: 'roles',
      render: (list: string[]) => (
        <Space size={4} wrap>
          {list.map((r) => (
            <Tag key={r} color={r === 'admin' ? 'red' : 'blue'}>
              {r}
            </Tag>
          ))}
        </Space>
      ),
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 90,
      render: (_: unknown, u: User) => (
        <Switch
          size="small"
          checked={u.status === 1}
          disabled={isSelf(u) || isAdminUser(u)}
          onChange={() => toggleStatus(u)}
        />
      ),
    },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      key: 'created_at',
      width: 170,
      render: (v: string) => formatTime(v),
    },
    {
      title: '操作',
      key: 'action',
      width: 120,
      render: (_: unknown, u: User) => (
        <Space>
          <Button
            type="text"
            size="small"
            icon={<EditOutlined />}
            onClick={() => openEdit(u)}
          />
          <Popconfirm
            title="确认删除该用户？"
            onConfirm={() => handleDelete(u)}
            disabled={isSelf(u) || isAdminUser(u)}
          >
            <Button
              type="text"
              danger
              size="small"
              icon={<DeleteOutlined />}
              disabled={isSelf(u) || isAdminUser(u)}
            />
          </Popconfirm>
        </Space>
      ),
    },
  ]

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 16 }}>
        <Input.Search
          placeholder="搜索用户名 / 邮箱"
          allowClear
          style={{ width: 280 }}
          onSearch={(v) => {
            setSearch(v)
            setPage(1)
            load(1, v)
          }}
        />
        <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>
          新建用户
        </Button>
      </div>

      {selectedKeys.length > 0 && (
        <Space style={{ marginBottom: 12 }} size={8}>
          <span style={{ fontSize: 13 }}>已选 {selectedKeys.length} 项</span>
          <Button size="small" onClick={() => batchSetStatus(1)}>
            批量启用
          </Button>
          <Button size="small" onClick={() => batchSetStatus(0)}>
            批量禁用
          </Button>
          <Popconfirm title={`确认删除选中的 ${selectedKeys.length} 个用户？`} onConfirm={batchDelete}>
            <Button size="small" danger>
              批量删除
            </Button>
          </Popconfirm>
        </Space>
      )}

      <Table
        rowKey="id"
        loading={loading}
        dataSource={users}
        columns={columns}
        rowSelection={{ selectedRowKeys: selectedKeys, onChange: setSelectedKeys }}
        pagination={{
          current: page,
          pageSize: PAGE_SIZE,
          total,
          showSizeChanger: false,
          onChange: (p) => {
            setPage(p)
            load(p, search)
          },
        }}
      />

      <Modal
        title={editing ? '编辑用户' : '新建用户'}
        open={modalOpen}
        onOk={handleSubmit}
        onCancel={() => setModalOpen(false)}
        confirmLoading={saving}
        destroyOnClose
      >
        <Form form={form} layout="vertical" style={{ marginTop: 12 }}>
          <Form.Item
            name="username"
            label="用户名"
            rules={[
              { required: true, message: '请输入用户名' },
              { pattern: /^[a-zA-Z0-9_]+$/, message: '仅字母/数字/下划线' },
            ]}
          >
            <Input disabled={!!editing} placeholder="3-50 字符" />
          </Form.Item>
          <Form.Item
            name="email"
            label="邮箱"
            rules={[
              { required: true, message: '请输入邮箱' },
              { type: 'email', message: '邮箱格式不正确' },
            ]}
          >
            <Input placeholder="user@example.com" />
          </Form.Item>
          <Form.Item
            name="password"
            label="密码"
            rules={editing ? [] : [{ required: true, message: '请输入密码' }]}
          >
            <Input.Password
              placeholder={editing ? '留空则不修改' : '至少 6 位'}
              autoComplete="new-password"
            />
          </Form.Item>
          <Form.Item name="role_ids" label="角色">
            <Select mode="multiple" options={roleOptions} placeholder="选择角色" />
          </Form.Item>
          <Form.Item name="status" label="状态" valuePropName="checked">
            <Switch checkedChildren="启用" unCheckedChildren="禁用" />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}
