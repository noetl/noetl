import React from 'react';
import ReactDOM from 'react-dom/client';
import { BrowserRouter as Router, Routes, Route } from 'react-router-dom';
import { Layout, Menu, Typography, ConfigProvider } from 'antd';
import { HomeOutlined, BookOutlined, EditOutlined, HistoryOutlined } from '@ant-design/icons';

// Import components
import Dashboard from './components/Dashboard';
import Catalog from './components/Catalog';
import Editor from './components/Editor';
import Execution from './components/Execution';

// Import styles
import 'antd/dist/reset.css';
import '../static/css/main.css';

const { Header, Content, Footer } = Layout;
const { Title } = Typography;

// Main App component
const App: React.FC = () => {
  return (
    <ConfigProvider theme={{ token: { colorPrimary: '#1890ff' } }}>
      <Router>
        <Layout style={{ minHeight: '100vh' }}>
          <Header className="app-header">
            <div className="logo">
              <Title level={4} style={{ color: 'white', margin: 0 }}>
                NoETL Dashboard
              </Title>
            </div>
            <Menu
              theme="dark"
              mode="horizontal"
              defaultSelectedKeys={['dashboard']}
              style={{ flex: 1, minWidth: 0 }}
              items={[
                {
                  key: 'dashboard',
                  icon: <HomeOutlined />,
                  label: 'Dashboard',
                  onClick: () => window.location.href = '/'
                },
                {
                  key: 'catalog',
                  icon: <BookOutlined />,
                  label: 'Catalog',
                  onClick: () => window.location.href = '/catalog'
                },
                {
                  key: 'editor',
                  icon: <EditOutlined />,
                  label: 'Editor',
                  onClick: () => window.location.href = '/editor'
                },
                {
                  key: 'execution',
                  icon: <HistoryOutlined />,
                  label: 'Execution',
                  onClick: () => window.location.href = '/execution'
                }
              ]}
            />
          </Header>
          <Content style={{ padding: '24px' }}>
            <Routes>
              <Route path="/" element={<Dashboard />} />
              <Route path="/catalog" element={<Catalog />} />
              <Route path="/editor" element={<Editor />} />
              <Route path="/execution" element={<Execution />} />
            </Routes>
          </Content>
          <Footer style={{ textAlign: 'center' }}>
            NoETL Dashboard ©2024 Created with React & TypeScript
          </Footer>
        </Layout>
      </Router>
    </ConfigProvider>
  );
};

// Mount the app
const root = ReactDOM.createRoot(document.getElementById('root') as HTMLElement);
root.render(<App />);
