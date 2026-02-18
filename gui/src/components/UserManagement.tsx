import { useEffect, useState } from "react";
import { Alert, Button, Card, Modal, Select, Space, Table, Tag, Typography, message } from "antd";
import { ReloadOutlined } from "@ant-design/icons";
import { useNavigate } from "react-router-dom";
import {
  connectSSE,
  disconnectSSE,
  executePlaybook,
  isAuthenticated,
  logout,
  subscribeConnection,
  validateSession,
} from "../services/gatewayAuth";

const { Title, Text } = Typography;

const USER_MGMT_PLAYBOOK = "api_integration/auth0/user_management";

interface User {
  user_id: number;
  email: string;
  display_name: string;
  roles: Array<{ role_id: number; role_name: string }>;
  last_login_at: string;
  is_active: boolean;
}

interface Role {
  role_id: number;
  role_name: string;
  description: string;
}

const UserManagement = () => {
  const navigate = useNavigate();
  const [users, setUsers] = useState<User[]>([]);
  const [roles, setRoles] = useState<Role[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [connectionReady, setConnectionReady] = useState(false);
  const [roleModalVisible, setRoleModalVisible] = useState(false);
  const [selectedUser, setSelectedUser] = useState<User | null>(null);
  const [selectedRoles, setSelectedRoles] = useState<string[]>([]);

  useEffect(() => {
    const initialize = async () => {
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
      } catch {
        logout();
        navigate("/login", { replace: true });
        return;
      }

      connectSSE();
    };

    const unsubscribeConnection = subscribeConnection((connected) => {
      setConnectionReady(connected);
      if (connected) {
        loadUsers();
        loadRoles();
      }
    });

    initialize();

    return () => {
      unsubscribeConnection();
      disconnectSSE();
    };
  }, [navigate]);

  const loadUsers = async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await executePlaybook(USER_MGMT_PLAYBOOK, { action: "list_users" });
      const data = result.data as { users?: User[]; success?: boolean; error?: string };

      if (data?.success === false) {
        throw new Error(data.error || "Failed to load users");
      }

      // Transform roles array to include role_name strings for display
      const usersWithRoles = (data?.users || []).map((user) => ({
        ...user,
        roles: user.roles || [],
      }));
      setUsers(usersWithRoles);
    } catch (err) {
      const detail = err instanceof Error ? err.message : "Failed to load users";
      if (detail === "Session expired" || detail === "Not authenticated") {
        logout();
        navigate("/login", { replace: true });
        return;
      }
      setError(detail);
    } finally {
      setLoading(false);
    }
  };

  const loadRoles = async () => {
    try {
      const result = await executePlaybook(USER_MGMT_PLAYBOOK, { action: "list_roles" });
      const data = result.data as { roles?: Role[]; success?: boolean };

      if (data?.success !== false) {
        setRoles(data?.roles || []);
      }
    } catch (err) {
      console.error("Failed to load roles:", err);
    }
  };

  const openRoleModal = (user: User) => {
    setSelectedUser(user);
    setSelectedRoles(user.roles?.map((r) => r.role_name) || []);
    setRoleModalVisible(true);
  };

  const handleRoleUpdate = async () => {
    if (!selectedUser) return;

    try {
      const result = await executePlaybook(USER_MGMT_PLAYBOOK, {
        action: "update_user_roles",
        user_id: selectedUser.user_id,
        role_names: selectedRoles,
      });

      const data = result.data as { success?: boolean; error?: string };
      if (data?.success === false) {
        throw new Error(data.error || "Failed to update roles");
      }

      message.success("Roles updated successfully");
      setRoleModalVisible(false);
      loadUsers();
    } catch (err) {
      message.error(err instanceof Error ? err.message : "Failed to update roles");
    }
  };

  const columns = [
    {
      title: "User ID",
      dataIndex: "user_id",
      key: "user_id",
      width: 100,
    },
    {
      title: "Email",
      dataIndex: "email",
      key: "email",
    },
    {
      title: "Name",
      dataIndex: "display_name",
      key: "display_name",
    },
    {
      title: "Roles",
      dataIndex: "roles",
      key: "roles",
      render: (roles: Array<{ role_id: number; role_name: string }>) => (
        <Space wrap>
          {(roles || []).map((role) => (
            <Tag
              key={role.role_id}
              color={role.role_name === "admin" ? "red" : role.role_name === "developer" ? "blue" : "default"}
            >
              {role.role_name}
            </Tag>
          ))}
        </Space>
      ),
    },
    {
      title: "Last Login",
      dataIndex: "last_login_at",
      key: "last_login_at",
      render: (date: string) => (date ? new Date(date).toLocaleString() : "Never"),
    },
    {
      title: "Status",
      dataIndex: "is_active",
      key: "is_active",
      render: (active: boolean) => (
        <Tag color={active ? "green" : "red"}>{active ? "Active" : "Inactive"}</Tag>
      ),
    },
    {
      title: "Actions",
      key: "actions",
      render: (_: unknown, record: User) => (
        <Button size="small" onClick={() => openRoleModal(record)} disabled={!connectionReady}>
          Manage Roles
        </Button>
      ),
    },
  ];

  const roleDescriptions: Record<string, string> = {
    admin: "Full system access",
    developer: "Create and manage playbooks",
    analyst: "Execute playbooks and view results",
    viewer: "View playbooks and execution history",
  };

  return (
    <div style={{ padding: "0" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 24 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <Title level={3} style={{ margin: 0 }}>
            User Management
          </Title>
          <Tag color={connectionReady ? "green" : "orange"}>
            {connectionReady ? "Connected" : "Connecting..."}
          </Tag>
        </div>
        <Button icon={<ReloadOutlined />} onClick={loadUsers} loading={loading} disabled={!connectionReady}>
          Refresh
        </Button>
      </div>

      {error && (
        <Alert
          type="error"
          message={error}
          showIcon
          closable
          onClose={() => setError(null)}
          style={{ marginBottom: 16 }}
        />
      )}

      {!connectionReady && (
        <Alert
          type="info"
          message="Establishing connection to gateway..."
          showIcon
          style={{ marginBottom: 16 }}
        />
      )}

      <Card title="Users" style={{ marginBottom: 24 }}>
        <Table
          dataSource={users}
          columns={columns}
          rowKey="user_id"
          loading={loading}
          pagination={{ pageSize: 10 }}
        />
      </Card>

      <Card title="Available Roles">
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(200px, 1fr))", gap: 16 }}>
          {roles.map((role) => (
            <Card key={role.role_id} size="small" style={{ background: "#fafafa" }}>
              <Text strong style={{ display: "block", marginBottom: 4 }}>
                {role.role_name}
              </Text>
              <Text type="secondary" style={{ fontSize: 12 }}>
                {role.description || roleDescriptions[role.role_name] || "No description"}
              </Text>
            </Card>
          ))}
        </div>
      </Card>

      <Modal
        title={`Manage Roles - ${selectedUser?.email}`}
        open={roleModalVisible}
        onOk={handleRoleUpdate}
        onCancel={() => setRoleModalVisible(false)}
      >
        <Select
          mode="multiple"
          style={{ width: "100%" }}
          placeholder="Select roles"
          value={selectedRoles}
          onChange={setSelectedRoles}
          options={roles.map((r) => ({ label: r.role_name, value: r.role_name }))}
        />
      </Modal>
    </div>
  );
};

export default UserManagement;
