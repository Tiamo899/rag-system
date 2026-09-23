import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import { ConfigProvider } from 'antd'
import zhCN from 'antd/locale/zh_CN'
import App from './App'
import './styles/global.css'

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <ConfigProvider
      locale={zhCN}
      theme={{
        token: {
          colorPrimary: '#6366f1',
          colorInfo: '#6366f1',
          colorLink: '#4f46e5',
          borderRadius: 10,
          fontFamily:
            "-apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC', 'Hiragino Sans GB', 'Microsoft YaHei', 'Helvetica Neue', Helvetica, Arial, sans-serif",
          colorText: '#0f172a',
          colorTextSecondary: '#64748b',
          controlHeight: 36,
          wireframe: false,
        },
        components: {
          Card: {
            borderRadiusLG: 16,
            paddingLG: 20,
          },
          Button: {
            borderRadius: 10,
            controlHeight: 36,
            fontWeight: 500,
          },
          Table: {
            headerBg: '#f8fafc',
            headerColor: '#334155',
            rowHoverBg: '#f6f7ff',
            borderColor: '#eef1f6',
          },
          Menu: {
            darkItemBg: 'transparent',
            darkSubMenuItemBg: 'transparent',
            itemBorderRadius: 10,
            itemMarginInline: 0,
          },
          Modal: {
            borderRadiusLG: 18,
          },
          Input: {
            borderRadius: 10,
            activeShadow: '0 0 0 3px rgba(99,102,241,0.14)',
          },
          Select: {
            borderRadius: 10,
          },
          Layout: {
            bodyBg: '#f4f6fb',
            headerBg: 'rgba(255,255,255,0.72)',
            siderBg: '#0b1426',
          },
          Tag: {
            borderRadiusSM: 8,
          },
        },
      }}
    >
      <BrowserRouter>
        <App />
      </BrowserRouter>
    </ConfigProvider>
  </React.StrictMode>
)
