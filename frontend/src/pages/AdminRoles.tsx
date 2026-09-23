import { useCallback, useEffect, useState } from 'react'
import type { Key } from 'react'
import {
  Button,
  Form,
  Input,
  Modal,
  Popconfirm,
  Space,
  Table,
  Tag,
  Tooltip,
  Tree,
  message,
} from 'antd'
import { DeleteOutlined, EditOutlined, PlusOutlined } from '@ant-design/icons'
import {
  createRole,
  deleteRole,
  listRolePermissions,
  listRoles,
  updateRole,
} from '../api/admin'
import { getErrorMessage } from '../api/http'
import { formatTime } from '../utils/time'
import type { PermissionNode, Role } from '../types'

const BUILTIN = ['admin', 'editor', 'viewer']

function buildTreeData(catalog: PermissionNode[]) {
  return catalog.map((g) => ({
    title: g.module,
    key: `module:${g.key}`,
    children: g.permissions.map((p) => ({ title: p.label, key: p.key })),
  }))
}

const leafKeys = (keys: React.Key[]): string[] =>
  keys.filter((k): k is string => !String(k).startsWith('module:'))

export default function AdminRoles() {
  const [roles, setRoles] = useState<Role[]>([])
  const [catalog, setCatalog] = useState<PermissionNode[]>([])
  const [loading, setLoading] = useState(false)
  const [modalOpen, setModalOpen] = useState(false)
  const [editing, setEditing] = useState<Role | null>(null)
  const [checkedKeys, setCheckedKeys] = useState<React.Key[]>([])
  const [selectedKeys, setSelectedKeys] = useState<Key[]>([])
  const [saving, setSaving] = useState(false)
  const [form] = Form.useForm()

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const [roleList, permCatalog] = await Promise.all([
        listRoles(),
        listRolePermissions(),
      ])
      setRoles(roleList)
      setCatalog(permCatalog)
    } catch (e) {
      message.error(getErrorMessage(e))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    load()
  }, [load])

  const isBuiltin = (r: Role) => BUILTIN.includes(r.name)

  const openCreate = () => {
    setEditing(null)
    form.resetFields()
    setCheckedKeys([])
    setModalOpen(true)
  }

  const openEdit = (role: Role) => {
    setEditing(role)
    form.setFieldsValue({ name: role.name, description: role.description })
    if (role.name === 'admin') {
      // admin 用 *:* 通配拥有全部权限，DB 里 permissions 为空，显示为全选（disabled）
      setCheckedKeys(catalog.flatMap((g) => g.permissions.map((p) => p.key)))
    } else {
      setCheckedKeys(role.permissions)
    }
    setModalOpen(true)
  }

  const handleSubmit = async () => {
    const values = await form.validateFields()
    setSaving(true)
    try {
      if (editing) {
        const payload: Record<string, unknown> = { description: values.description }
        if (!isBuiltin(editing)) {
          payload.name = values.name
          payload.permissions = leafKeys(checkedKeys)
        }
        await updateRole(editing.id, payload)
        message.success('已保存')
      } else {
        await createRole({
          name: values.name,
          description: values.description,
          permissions: leafKeys(checkedKeys),
        })
        message.success('已创建')
      }
      setModalOpen(false)
      load()
    } catch (e) {
      message.error(getErrorMessage(e))
    } finally {
      setSaving(false)
    }
  }

  const handleDelete = async (role: Role) => {
    try {
      await deleteRole(role.id)
      message.success('已删除')
      load()
    } catch (e) {
      message.error(getErrorMessage(e))
    }
  }

  const batchDelete = async () => {
    if (!selectedKeys.length) return
    const targets = roles.filter((r) => selectedKeys.includes(r.id))
    const builtin = targets.filter((r) => BUILTIN.includes(r.name))
    const valid = targets.filter((r) => !builtin.includes(r))
    try {
      for (const r of valid) await deleteRole(r.id)
      message.success(
        builtin.length
          ? `已删除 ${valid.length} 个，${builtin.length} 个内置角色跳过`
          : `已删除 ${valid.length} 个角色`
      )
      setSelectedKeys([])
      load()
    } catch (e) {
      message.error(getErrorMessage(e))
    }
  }

  const treeData = buildTreeData(catalog)
  // 内置角色（admin/editor/viewer）权限不可修改，树 disabled
  const treeDisabled = editing ? isBuiltin(editing) : false

  const columns = [
    {
      title: '角色名',
      dataIndex: 'name',
      key: 'name',
      render: (name: string) =>
        isBuiltin({ name } as Role) ? <Tag color="gold">{name}</Tag> : name,
    },
    { title: '描述', dataIndex: 'description', key: 'description', ellipsis: true },
    {
      title: '权限',
      dataIndex: 'permissions',
      key: 'permissions',
      width: 160,
      render: (perms: string[], r: Role) =>
        r.name === 'admin' ? (
          <Tag color="red">*:* 全部权限</Tag>
        ) : (
          <Tooltip title={perms.join(', ')}>
            <Tag color="blue">{perms.length} 项</Tag>
          </Tooltip>
        ),
    },
    { title: '用户数', dataIndex: 'user_count', key: 'user_count', width: 90 },
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
      render: (_: unknown, r: Role) => (
        <Space>
          <Button type="text" size="small" icon={<EditOutlined />} onClick={() => openEdit(r)} />
          <Popconfirm
            title="确认删除该角色？"
            onConfirm={() => handleDelete(r)}
            disabled={isBuiltin(r)}
          >
            <Button
              type="text"
              danger
              size="small"
              icon={<DeleteOutlined />}
              disabled={isBuiltin(r)}
            />
          </Popconfirm>
        </Space>
      ),
    },
  ]

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 16 }}>
        {selectedKeys.length > 0 ? (
          <Space size={8}>
            <span style={{ fontSize: 13 }}>已选 {selectedKeys.length} 项</span>
            <Popconfirm
              title={`确认删除选中的 ${selectedKeys.length} 个角色？`}
              onConfirm={batchDelete}
            >
              <Button size="small" danger>
                批量删除
              </Button>
            </Popconfirm>
          </Space>
        ) : (
          <span />
        )}
        <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>
          新建角色
        </Button>
      </div>

      <Table
        rowKey="id"
        loading={loading}
        dataSource={roles}
        columns={columns}
        pagination={false}
        rowSelection={{ selectedRowKeys: selectedKeys, onChange: setSelectedKeys }}
      />

      <Modal
        title={editing ? '编辑角色' : '新建角色'}
        open={modalOpen}
        onOk={handleSubmit}
        onCancel={() => setModalOpen(false)}
        confirmLoading={saving}
        destroyOnClose
        width={520}
      >
        <Form form={form} layout="vertical" style={{ marginTop: 12 }}>
          <Form.Item
            name="name"
            label="角色名"
            rules={[
              { required: true, message: '请输入角色名' },
              { pattern: /^[a-zA-Z0-9_]+$/, message: '仅字母/数字/下划线' },
            ]}
          >
            <Input disabled={isBuiltin(editing ?? ({ name: '' } as Role))} placeholder="如：operator" />
          </Form.Item>
          <Form.Item name="description" label="描述">
            <Input placeholder="角色用途说明" />
          </Form.Item>
          <Form.Item label="权限" style={{ marginBottom: 0 }}>
            <Tree
              checkable
              defaultExpandAll
              disabled={treeDisabled}
              checkedKeys={checkedKeys}
              onCheck={(keys) => setCheckedKeys(keys as React.Key[])}
              treeData={treeData}
            />
          </Form.Item>
          {editing?.name === 'admin' && (
            <div style={{ color: '#999', fontSize: 12, marginTop: 8 }}>
              管理员拥有全部权限（*:*），不可修改。
            </div>
          )}
          {isBuiltin(editing ?? ({ name: '' } as Role)) && editing?.name !== 'admin' && (
            <div style={{ color: '#999', fontSize: 12, marginTop: 8 }}>
              内置角色仅允许修改描述，权限不可修改。
            </div>
          )}
        </Form>
      </Modal>
    </div>
  )
}
