import type { ReactNode } from 'react'
import { Navigate, Route, Routes, useLocation, useNavigate } from 'react-router-dom'
import { Avatar, Dropdown, Layout, Menu, Typography } from 'antd'
import {
  DashboardOutlined,
  DatabaseOutlined,
  LogoutOutlined,
  RobotOutlined,
  SettingOutlined,
  UserOutlined,
} from '@ant-design/icons'
import { useAuthStore } from './store/auth'
import Login from './pages/Login'
import Dashboard from './pages/Dashboard'
import KnowledgeBase from './pages/KnowledgeBase'
import Chat from './pages/Chat'
import AdminUsers from './pages/AdminUsers'
import AdminRoles from './pages/AdminRoles'
import AdminSettings from './pages/AdminSettings'

const { Sider, Header, Content } = Layout

const PAGE_TITLES: Record<string, string> = {
  '/': '数据概览',
  '/knowledge-base': '知识库管理',
  '/chat': '智能问答',
  '/admin/users': '用户管理',
  '/admin/roles': '角色管理',
  '/admin/settings': '系统设置',
}

function Shell() {
  const { user, logout } = useAuthStore()
  const navigate = useNavigate()
  const location = useLocation()
  const isAdmin = user?.roles?.includes('admin') ?? false

  const pageTitle = PAGE_TITLES[location.pathname] ?? '高校教务智能问答系统'

  const navItems = [
    { key: '/', icon: <DashboardOutlined />, label: '数据概览' },
    { key: '/knowledge-base', icon: <DatabaseOutlined />, label: '知识库' },
    { key: '/chat', icon: <RobotOutlined />, label: '智能问答' },
    ...(isAdmin
      ? [
          {
            key: '/admin',
            icon: <SettingOutlined />,
            label: '系统管理',
            children: [
              { key: '/admin/users', label: '用户管理' },
              { key: '/admin/roles', label: '角色管理' },
              { key: '/admin/settings', label: '系统设置' },
            ],
          },
        ]
      : []),
  ]

  const adminRoute = (element: ReactNode) =>
    isAdmin ? element : <Navigate to="/" replace />

  return (
    <Layout style={{ minHeight: '100vh', background: 'linear-gradient(180deg,#f6f8fc 0%,#eef2f8 100%)' }}>
      <Sider
        width={232}
        className="app-sider"
        style={{
          position: 'sticky',
          top: 0,
          height: '100vh',
          overflow: 'auto',
        }}
      >
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 12,
            padding: '20px 18px 16px',
            color: '#fff',
            fontSize: 15.5,
            fontWeight: 700,
            letterSpacing: 0.4,
          }}
        >
          <span
            className="sider-logo-badge"
            style={{
              width: 40,
              height: 40,
              borderRadius: 12,
              display: 'inline-flex',
              alignItems: 'center',
              justifyContent: 'center',
              fontSize: 21,
              color: '#fff',
              flexShrink: 0,
            }}
          >
            <RobotOutlined />
          </span>
          <span style={{ lineHeight: 1.35 }}>
            高校教务
            <br />
            <span style={{ fontSize: 13, fontWeight: 500, color: 'rgba(226,232,240,0.72)' }}>
              智能问答系统
            </span>
          </span>
        </div>

        <Menu
          theme="dark"
          mode="inline"
          defaultOpenKeys={['/admin']}
          selectedKeys={[location.pathname]}
          onClick={({ key }) => navigate(key)}
          items={navItems}
        />
      </Sider>

      <Layout style={{ background: 'transparent' }}>
        <Header
          className="app-header"
          style={{
            padding: '0 28px',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            position: 'sticky',
            top: 0,
            zIndex: 10,
            height: 62,
          }}
        >
          <Typography.Title level={5} style={{ margin: 0, color: '#0f172a', fontWeight: 700, letterSpacing: 0.3 }}>
            {pageTitle}
          </Typography.Title>

          <Dropdown
            trigger={['click']}
            menu={{
              items: [
                { key: 'logout', icon: <LogoutOutlined />, label: '退出登录', onClick: () => { logout(); navigate('/login') } },
              ],
            }}
          >
            <span className="user-chip" style={{ cursor: 'pointer', display: 'inline-flex', alignItems: 'center', gap: 8 }}>
              <Avatar size="small" icon={<UserOutlined />} className="avatar-user" />
              <span style={{ color: '#334155', fontWeight: 500 }}>{user?.username ?? '未登录'}</span>
            </span>
          </Dropdown>
        </Header>

        <Content
          style={{
            margin: 20,
            padding: 4,
            background: 'transparent',
            minHeight: 'calc(100vh - 102px)',
          }}
        >
          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route path="/knowledge-base" element={<KnowledgeBase />} />
            <Route path="/chat" element={<Chat />} />
            <Route path="/admin" element={adminRoute(<Navigate to="/admin/users" replace />)} />
            <Route path="/admin/users" element={adminRoute(<AdminUsers />)} />
            <Route path="/admin/roles" element={adminRoute(<AdminRoles />)} />
            <Route path="/admin/settings" element={adminRoute(<AdminSettings />)} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </Content>
      </Layout>
    </Layout>
  )
}

export default function App() {
  const token = useAuthStore((s) => s.token)
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route path="/*" element={token ? <Shell /> : <Navigate to="/login" replace />} />
    </Routes>
  )
}
