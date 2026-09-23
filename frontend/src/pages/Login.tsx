import { useEffect, useState } from 'react'
import { Button, Form, Input, Typography, message } from 'antd'
import {
  DatabaseOutlined,
  LockOutlined,
  RobotOutlined,
  SafetyOutlined,
  ThunderboltOutlined,
  UserOutlined,
} from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import { login } from '../api/auth'
import { getErrorMessage } from '../api/http'
import { useAuthStore } from '../store/auth'

const { Title, Paragraph, Text } = Typography

const FEATURES = [
  { icon: <DatabaseOutlined />, text: '混合检索，多知识库智能问答' },
  { icon: <ThunderboltOutlined />, text: '流式输出，实时思考过程' },
  { icon: <SafetyOutlined />, text: '细粒度角色权限管理' },
]

export default function Login() {
  const navigate = useNavigate()
  const setAuth = useAuthStore((s) => s.setAuth)
  const [loading, setLoading] = useState(false)
  const [narrow, setNarrow] = useState(() => window.innerWidth < 900)

  useEffect(() => {
    const onResize = () => setNarrow(window.innerWidth < 900)
    window.addEventListener('resize', onResize)
    return () => window.removeEventListener('resize', onResize)
  }, [])

  const onFinish = async (values: { username: string; password: string }) => {
    setLoading(true)
    try {
      const data = await login(values.username, values.password)
      setAuth(data.access_token, data.user)
      message.success('登录成功')
      navigate('/')
    } catch (e) {
      message.error(getErrorMessage(e))
    } finally {
      setLoading(false)
    }
  }

  return (
    <div
      className="login-shell"
      style={{
        minHeight: '100vh',
        display: 'flex',
      }}
    >
      {/* 左侧品牌区 */}
      <div
        className="login-brand"
        style={{
          flex: 1,
          display: narrow ? 'none' : 'flex',
          flexDirection: 'column',
          justifyContent: 'center',
          padding: '56px 72px',
        }}
      >
        <div className="login-grid" />

        <div style={{ position: 'relative', zIndex: 1, maxWidth: 460 }}>
          <div
            className="sider-logo-badge"
            style={{
              width: 76,
              height: 76,
              borderRadius: 22,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              fontSize: 38,
              color: '#fff',
              marginBottom: 30,
            }}
          >
            <RobotOutlined />
          </div>

          <Title level={1} style={{ color: '#fff', marginBottom: 14, fontSize: 42, lineHeight: 1.2, fontWeight: 800 }}>
            高校教务
            <span className="brand-text-gradient">智能问答</span>
          </Title>
          <Paragraph style={{ color: 'rgba(226,232,240,0.78)', fontSize: 16.5, marginBottom: 44, lineHeight: 1.8 }}>
            导入教务政策与学生服务文档，学生随时问、答案带出处。智能问答、语义检索、权限管控一站完成。
          </Paragraph>

          <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
            {FEATURES.map((f) => (
              <div
                key={f.text}
                style={{ display: 'flex', alignItems: 'center', gap: 16, fontSize: 15.5, color: '#e2e8f0' }}
              >
                <span
                  className="login-feature-icon"
                  style={{
                    width: 44,
                    height: 44,
                    borderRadius: 14,
                    display: 'inline-flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    fontSize: 19,
                    flexShrink: 0,
                  }}
                >
                  {f.icon}
                </span>
                <span>{f.text}</span>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* 右侧登录卡片 */}
      <div
        style={{
          width: narrow ? '100%' : 480,
          minWidth: 380,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          padding: '32px 40px',
        }}
      >
        <div
          className="login-card"
          style={{
            width: '100%',
            maxWidth: 392,
            padding: '44px 38px 34px',
          }}
        >
          <Title level={3} style={{ marginBottom: 6, textAlign: 'center', color: '#0f172a', fontWeight: 700 }}>
            欢迎回来
          </Title>
          <Paragraph type="secondary" style={{ textAlign: 'center', marginBottom: 34 }}>
            登录账号，进入教务智能问答平台
          </Paragraph>

          <Form onFinish={onFinish} size="large" autoComplete="off">
            <Form.Item name="username" rules={[{ required: true, message: '请输入用户名' }]}>
              <Input prefix={<UserOutlined style={{ color: '#94a3b8' }} />} placeholder="用户名" autoFocus size="large" />
            </Form.Item>
            <Form.Item name="password" rules={[{ required: true, message: '请输入密码' }]}>
              <Input.Password
                prefix={<LockOutlined style={{ color: '#94a3b8' }} />}
                placeholder="密码"
                autoComplete="current-password"
                size="large"
              />
            </Form.Item>
            <Button
              type="primary"
              htmlType="submit"
              block
              loading={loading}
              style={{
                height: 46,
                fontSize: 15,
                marginTop: 4,
              }}
            >
              登 录
            </Button>
          </Form>

          <Text type="secondary" style={{ display: 'block', textAlign: 'center', marginTop: 26, fontSize: 12 }}>
            账号由系统管理员分配，如有问题请联系管理员
          </Text>
        </div>
      </div>
    </div>
  )
}
