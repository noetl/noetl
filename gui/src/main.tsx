import { useState, useEffect, useMemo } from "react";
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
import { Layout, Menu, ConfigProvider, Result, Button, App as AntdApp, Spin } from "antd";

// Import components
import Catalog from "./components/Catalog";
import Credentials from "./components/Credentials";
import Editor from "./components/Editor";
import Execution from "./components/Execution";
import ExecutionDetail from "./components/ExecutionDetail";
import GatewayLogin from "./components/GatewayLogin";
import GatewayAssistant from "./components/GatewayAssistant";
import UserManagement from "./components/UserManagement";

// Import auth functions
import { isAuthenticated, getUserInfo, validateSession, logout, type GatewayUser } from "./services/gatewayAuth";

// Import styles
import "antd/dist/reset.css";
import "../static/css/main.css";

const { Header, Content, Footer } = Layout;

// Define menu items with required roles
// admin: sees all, developer: sees noetl tools, analyst/viewer: sees travel only
type MenuItem = {
  key: string;
  label: string;
  path: string;
  roles: string[]; // empty array means all authenticated users, specific roles restrict access
  adminOnly?: boolean; // if true, only admin can see
};

const ALL_MENU_ITEMS: MenuItem[] = [
  { key: "/catalog", label: "Catalog", path: "/catalog", roles: [], adminOnly: true },
  { key: "/credentials", label: "Credentials", path: "/credentials", roles: [], adminOnly: true },
  { key: "/editor", label: "Editor", path: "/editor", roles: [], adminOnly: true },
  { key: "/execution", label: "Execution", path: "/execution", roles: [], adminOnly: true },
  { key: "/travel", label: "Travel", path: "/travel", roles: ["analyst", "viewer", "developer", "admin"] },
  { key: "/users", label: "Users", path: "/users", roles: [], adminOnly: true },
];

function hasAccess(item: MenuItem, userRoles: string[]): boolean {
  // Admin has access to everything
  if (userRoles.includes("admin")) {
    return true;
  }
  // Admin-only items are not accessible to non-admins
  if (item.adminOnly) {
    return false;
  }
  // If no roles specified, all authenticated users have access
  if (item.roles.length === 0) {
    return true;
  }
  // Check if user has any of the required roles
  return item.roles.some((role) => userRoles.includes(role));
}

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

// Access Denied component
const AccessDenied: React.FC = () => {
  const navigate = useNavigate();

  return (
    <Result
      status="403"
      title="Access Denied"
      subTitle="You don't have permission to access this page."
      extra={
        <Button type="primary" onClick={() => navigate("/")}>
          Back Home
        </Button>
      }
    />
  );
};

// Login page wrapper (no layout/menu)
const LoginPage: React.FC = () => {
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
        <div style={{ minHeight: "100vh", background: "#f5f5f5", display: "flex", alignItems: "center", justifyContent: "center" }}>
          <GatewayLogin />
        </div>
      </AntdApp>
    </ConfigProvider>
  );
};

// Main authenticated app with menu
const AuthenticatedApp: React.FC = () => {
  const navigate = useNavigate();
  const location = useLocation();
  const [user, setUser] = useState<GatewayUser | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const checkAuth = async () => {
      if (!isAuthenticated()) {
        navigate("/login", { replace: true });
        return;
      }

      try {
        const valid = await validateSession();
        if (!valid) {
          logout();
          navigate("/login", { replace: true });
          return;
        }
        setUser(getUserInfo());
      } catch {
        logout();
        navigate("/login", { replace: true });
      } finally {
        setLoading(false);
      }
    };

    checkAuth();
  }, [navigate]);

  const userRoles = useMemo(() => {
    return user?.roles || [];
  }, [user]);

  const visibleMenuItems = useMemo(() => {
    return ALL_MENU_ITEMS.filter((item) => hasAccess(item, userRoles));
  }, [userRoles]);

  const activeMenuKey = useMemo(() => {
    // Find the menu item that matches current path
    const match = visibleMenuItems.find((item) => location.pathname.startsWith(item.key));
    return match?.key || "";
  }, [location.pathname, visibleMenuItems]);

  if (loading) {
    return (
      <div style={{ minHeight: "100vh", display: "flex", alignItems: "center", justifyContent: "center" }}>
        <Spin size="large" />
      </div>
    );
  }

  const handleLogout = () => {
    logout();
    navigate("/login", { replace: true });
  };

  return (
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
              ...visibleMenuItems.map((item) => ({
                key: item.key,
                label: item.label,
                onClick: () => navigate(item.path),
              })),
              {
                key: "logout",
                label: "Logout",
                onClick: handleLogout,
                style: { marginLeft: "auto" },
              },
            ]}
          />
        </div>
      </Header>
      <Content style={{ padding: "24px", margin: "0 24px" }}>
        <div
          className="AppRoutesContent"
          style={{
            background: "#fff",
            padding: "24px",
            borderRadius: "12px",
            boxShadow: "0 2px 8px rgba(0, 0, 0, 0.06)",
          }}
        >
          <Routes>
            <Route
              path="/"
              element={
                visibleMenuItems[0] ? (
                  <Navigate to={visibleMenuItems[0].path} replace />
                ) : (
                  <AccessDenied />
                )
              }
            />
            <Route path="/catalog" element={userRoles.includes("admin") ? <Catalog /> : <AccessDenied />} />
            <Route path="/credentials" element={userRoles.includes("admin") ? <Credentials /> : <AccessDenied />} />
            <Route path="/editor" element={userRoles.includes("admin") ? <Editor /> : <AccessDenied />} />
            <Route path="/execution" element={userRoles.includes("admin") ? <Execution /> : <AccessDenied />} />
            <Route path="/execution/:id" element={userRoles.includes("admin") ? <ExecutionDetail /> : <AccessDenied />} />
            <Route path="/travel" element={<GatewayAssistant />} />
            <Route path="/users" element={userRoles.includes("admin") ? <UserManagement /> : <AccessDenied />} />
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
        NoETL 2025
      </Footer>
    </Layout>
  );
};

// Root App component - handles routing between login and authenticated app
const App: React.FC = () => {
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
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route path="/*" element={<AuthenticatedApp />} />
        </Routes>
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
