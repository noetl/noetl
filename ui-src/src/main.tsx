import { useState, useEffect } from "react";
import type React from "react";
import { createRoot } from "react-dom/client";
import {
  createBrowserRouter,
  RouterProvider,
  Routes,
  Route,
  useNavigate,
  useLocation,
  Navigate,
} from "react-router-dom";
import { Layout, Menu, Typography, ConfigProvider, Result, Button } from "antd";
import {
  HomeOutlined,
  BookOutlined,
  EditOutlined,
  HistoryOutlined,
} from "@ant-design/icons";

// Import components
import Dashboard from "./components/Dashboard";
import Catalog from "./components/Catalog";
import Editor from "./components/Editor";
import Execution from "./components/Execution";
import ExecutionDetail from "./components/ExecutionDetail";

// Import styles
import "antd/dist/reset.css";
import "../static/css/main.css";

const { Header, Content, Footer } = Layout;
const { Title } = Typography;

// 404 Not Found component
const NotFound: React.FC = () => {
  const navigate = useNavigate();

  return (
    <Result
      status="404"
      title="404"
      subTitle="Sorry, the page you visited does not exist."
      extra={
        <Button type="primary" onClick={() => navigate("/")}>
          Back Home
        </Button>
      }
    />
  );
};

// Main App component
const App: React.FC = () => {
  const navigate = useNavigate();
  const location = useLocation();
  const [selectedKey, setSelectedKey] = useState(() => {
    if (location.pathname.startsWith("/catalog")) return "catalog";
    if (location.pathname.startsWith("/editor")) return "editor";
    if (location.pathname.startsWith("/execution")) return "execution";
    return "dashboard";
  });

  useEffect(() => {
    if (location.pathname.startsWith("/catalog")) setSelectedKey("catalog");
    else if (location.pathname.startsWith("/editor")) setSelectedKey("editor");
    else if (location.pathname.startsWith("/execution"))
      setSelectedKey("execution");
    else setSelectedKey("dashboard");
  }, [location.pathname]);

  return (
    <ConfigProvider
      theme={{
        token: {
          colorPrimary: "#1890ff",
          borderRadius: 8,
          colorBgContainer: "#ffffff",
          colorBgLayout: "#f5f5f5",
        },
      }}
    >
      <Layout style={{ minHeight: "100vh", background: "#f5f5f5" }}>
        <Header className="app-header">
          <div className="header-inner">
            <div className="logo">NoETL Dashboard</div>
            <Menu
              theme="light"
              mode="horizontal"
              selectedKeys={[selectedKey]}
              className="centered-menu"
              items={[
                {
                  key: "dashboard",
                  label: "Dashboard",
                  onClick: () => navigate("/"),
                },
                {
                  key: "catalog",
                  label: "Catalog",
                  onClick: () => navigate("/catalog"),
                },
                {
                  key: "editor",
                  label: "Editor",
                  onClick: () => navigate("/editor"),
                },
                {
                  key: "execution",
                  label: "Execution",
                  onClick: () => navigate("/execution"),
                },
              ]}
            />
          </div>
        </Header>
        <Content style={{ padding: "24px", margin: "0 24px" }}>
          <div
            style={{
              background: "#fff",
              padding: "24px",
              borderRadius: "12px",
              boxShadow: "0 2px 8px rgba(0, 0, 0, 0.06)",
              minHeight: "calc(100vh - 200px)",
            }}
          >
            <Routes>
              <Route path="/" element={<Dashboard />} />
              <Route path="/catalog" element={<Catalog />} />
              <Route path="/editor" element={<Editor />} />
              <Route path="/execution" element={<Execution />} />
              <Route path="/execution/:id" element={<ExecutionDetail />} />
              {/* Catch-all route for 404 */}
              <Route path="*" element={<NotFound />} />
            </Routes>
          </div>
        </Content>
        <Footer
          style={{
            textAlign: "center",
            background: "transparent",
            color: "#8c8c8c",
            fontSize: "14px",
          }}
        >
          NoETL Dashboard ©2024 Created with React & TypeScript
        </Footer>
      </Layout>
    </ConfigProvider>
  );
};

// Mount the app
const root = createRoot(document.getElementById("root") as HTMLElement);
const router = createBrowserRouter(
  [
    {
      path: "/*",
      element: <App />,
    },
  ],
  // Opt-in to v7 behaviors to avoid future flag warnings. Cast to any to satisfy TS.
  ({
    future: {
      v7_startTransition: true,
      v7_relativeSplatPath: true,
    },
  } as any),
);

root.render(<RouterProvider router={router} />);
