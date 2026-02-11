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
} from "react-router-dom";
import { Layout, Menu, Typography, ConfigProvider, Result, Button, App as AntdApp } from "antd";

// Import components
import Catalog from "./components/Catalog";
import Credentials from "./components/Credentials";
import Editor from "./components/Editor";
import Execution from "./components/Execution";
import ExecutionDetail from "./components/ExecutionDetail";
import GatewayLogin from "./components/GatewayLogin";
import GatewayAssistant from "./components/GatewayAssistant";

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
  const activeMenuKey = location.pathname.startsWith("/gateway")
    ? "/gateway"
    : location.pathname;

  useEffect(() => {
    // navigate("/catalog");
  }, []);

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
      <AntdApp>
        <Layout className="app" style={{ minHeight: "100vh", background: "#f5f5f5" }}>
          <Header className="app-header">
            <div className="header-inner">
              <div className="logo">NoETL Dashboard</div>
              <Menu
                theme="light"
                mode="horizontal"
                selectedKeys={[activeMenuKey]}
                className="centered-menu"
                items={[
                  {
                    key: "/catalog",
                    label: "Catalog",
                    onClick: () => navigate("/catalog"),
                  },
                  {
                    key: "/credentials",
                    label: "Credentials",
                    onClick: () => navigate("/credentials"),
                  },
                  {
                    key: "/editor",
                    label: "Editor",
                    onClick: () => navigate("/editor"),
                  },
                  {
                    key: "/execution",
                    label: "Execution",
                    onClick: () => navigate("/execution"),
                  },
                  {
                    key: "/gateway",
                    label: "Gateway",
                    onClick: () => navigate("/gateway"),
                  },
                ]}
              />
            </div>
          </Header>
          <Content style={{ padding: "24px", margin: "0 24px" }}>
            <div className="AppRoutesContent"
              style={{
                background: "#fff",
                padding: "24px",
                borderRadius: "12px",
                boxShadow: "0 2px 8px rgba(0, 0, 0, 0.06)",
                // minHeight: "calc(100vh - 200px)",
              }}
            >
              <Routes>
                <Route path="/catalog" element={<Catalog />} />
                <Route path="/credentials" element={<Credentials />} />
                <Route path="/editor" element={<Editor />} />
                <Route path="/execution" element={<Execution />} />
                <Route path="/execution/:id" element={<ExecutionDetail />} />
                <Route path="/gateway/login" element={<GatewayLogin />} />
                <Route path="/gateway" element={<GatewayAssistant />} />
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
            NoETL ©2025
          </Footer>
        </Layout>
      </AntdApp>
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
