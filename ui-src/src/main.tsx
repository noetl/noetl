import React, { useState } from 'react';
import ReactDOM from 'react-dom/client';
import { BrowserRouter as Router, Routes, Route, useNavigate, useLocation } from 'react-router-dom';
import { Layout, Menu, Typography, ConfigProvider } from 'antd';
import { HomeOutlined, BookOutlined, EditOutlined, HistoryOutlined } from '@ant-design/icons';

// Import components
import Dashboard from './components/Dashboard';
import Catalog from './components/Catalog';
import Editor from './components/Editor';
import Execution from './components/Execution';
import ExecutionDetail from './components/ExecutionDetail';

// Import styles
import 'antd/dist/reset.css';
import '../static/css/main.css';

const { Header, Content, Footer } = Layout;
const { Title } = Typography;

// Main App component
const App: React.FC = () => {
  const navigate = useNavigate();
  const location = useLocation();
  const [selectedKey, setSelectedKey] = useState(() => {
    if (location.pathname.startsWith('/catalog')) return 'catalog';
    if (location.pathname.startsWith('/editor')) return 'editor';
    if (location.pathname.startsWith('/execution')) return 'execution';
    return 'dashboard';
  });

  React.useEffect(() => {
    if (location.pathname.startsWith('/catalog')) setSelectedKey('catalog');
    else if (location.pathname.startsWith('/editor')) setSelectedKey('editor');
    else if (location.pathname.startsWith('/execution')) setSelectedKey('execution');
    else setSelectedKey('dashboard');
  }, [location.pathname]);

  return (
    <ConfigProvider theme={{ token: { colorPrimary: '#1890ff' } }}>
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
            selectedKeys={[selectedKey]}
            style={{ flex: 1, minWidth: 0 }}
            items={[
              {
                key: 'dashboard',
                icon: <HomeOutlined />,
                label: 'Dashboard',
                onClick: () => navigate('/')
              },
              {
                key: 'catalog',
                icon: <BookOutlined />,
                label: 'Catalog',
                onClick: () => navigate('/catalog')
              },
              {
                key: 'editor',
                icon: <EditOutlined />,
                label: 'Editor',
                onClick: () => navigate('/editor')
              },
              {
                key: 'execution',
                icon: <HistoryOutlined />,
                label: 'Execution',
                onClick: () => navigate('/execution')
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
            <Route path="/execution/:id" element={<ExecutionDetail />} />
          </Routes>
        </Content>
        <Footer style={{ textAlign: 'center' }}>
          NoETL Dashboard ©2024 Created with React & TypeScript
        </Footer>
      </Layout>
    </ConfigProvider>
  );
};

// Mount the app
const root = ReactDOM.createRoot(document.getElementById('root') as HTMLElement);
root.render(
  <Router>
    <App />
  </Router>
);
