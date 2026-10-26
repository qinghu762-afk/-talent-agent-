import { lazy, Suspense, useEffect, useState } from "react";
import {
  App as AntApp,
  Alert,
  Avatar,
  Badge,
  Button,
  Card,
  Drawer,
  Form,
  Input,
  Layout,
  Menu,
  Space,
  Spin,
  Typography,
} from "antd";
import {
  AuditOutlined,
  CloudUploadOutlined,
  DatabaseOutlined,
  LogoutOutlined,
  SafetyCertificateOutlined,
  TeamOutlined,
  UserOutlined,
} from "@ant-design/icons";
import { api, useResource } from "./api";
import type { System, User } from "./types";
import TasksPage from "./TasksPage";
import TalentsPage from "./TalentsPage";
import IssuesPage from "./IssuesPage";
const JobsPage = lazy(() => import("./JobsPage"));
import AccountsPage from "./AccountsPage";
import { ErrorPanel } from "./ui";
const pages = [
  { key: "tasks", label: "任务中心", icon: <CloudUploadOutlined /> },
  { key: "talents", label: "人才库", icon: <TeamOutlined /> },
  { key: "issues", label: "异常与重复", icon: <AuditOutlined /> },
  { key: "jobs", label: "岗位与匹配", icon: <DatabaseOutlined /> },
  { key: "accounts", label: "账号管理", icon: <UserOutlined /> },
];
export default function App() {
  const [user, setUser] = useState<User | null>(null);
  const [checking, setChecking] = useState(true);
  const [initialError, setInitialError] = useState("");
  const [page, setPage] = useState("tasks");
  const [systemOpen, setSystemOpen] = useState(false);
  const system = useResource<System>(user ? "/system" : null);
  const { message } = AntApp.useApp();
  useEffect(() => {
    let alive = true;
    api<User>("/auth/me")
      .then((value) => {
        if (alive) setUser(value);
      })
      .catch((e) => {
        if (alive && e.status !== 401) setInitialError(e.message);
      })
      .finally(() => {
        if (alive) setChecking(false);
      });
    const expired = () => {
      setUser(null);
      setPage("tasks");
    };
    window.addEventListener("session-expired", expired);
    return () => {
      alive = false;
      window.removeEventListener("session-expired", expired);
    };
  }, []);
  if (checking)
    return (
      <div className="full-center">
        <Spin tip="正在检查登录状态" size="large">
          <div className="spinner-space" />
        </Spin>
      </div>
    );
  if (!user) return <Login onLogin={setUser} initialError={initialError} />;
  const menus = pages.filter(
    (item) => item.key !== "accounts" || user.role === "admin",
  );
  const current = menus.find((item) => item.key === page) || menus[0];
  const healthy = system.data
    ? Object.values(system.data.services).every((service) => service.ok)
    : false;
  async function logout() {
    try {
      await api("/auth/logout", { method: "POST" });
      setUser(null);
      setPage("tasks");
    } catch (e) {
      message.error((e as Error).message);
    }
  }
  return (
    <Layout className="app-shell">
      <Layout.Sider
        width={222}
        breakpoint="lg"
        collapsedWidth={64}
        className="rail"
      >
        <div className="brand">
          <div className="brand-mark">才</div>
          <div className="brand-word">
            人才档案<span>私有工作台</span>
          </div>
        </div>
        <Menu
          mode="inline"
          theme="dark"
          selectedKeys={[current.key]}
          items={menus}
          onClick={({ key }) => setPage(key)}
        />
        <div className="rail-bottom">
          <SafetyCertificateOutlined />
          <span>本地处理 · 私有存储</span>
        </div>
      </Layout.Sider>
      <Layout>
        <header className="topbar">
          <span className="breadcrumb">
            人才档案 / <strong>{current.label}</strong>
          </span>
          <Space size={20}>
            <Button
              type="text"
              onClick={() => {
                system.reload();
                setSystemOpen(true);
              }}
            >
              <Badge
                status={healthy ? "success" : "warning"}
                text={
                  system.loading
                    ? "检查中"
                    : healthy
                      ? "系统就绪"
                      : "系统待检查"
                }
              />
            </Button>
            <Space>
              <Avatar size={30} icon={<UserOutlined />} />
              <span className="username">{user.username}</span>
            </Space>
            <Button
              aria-label="退出登录"
              title="退出登录"
              type="text"
              icon={<LogoutOutlined />}
              onClick={logout}
            />
          </Space>
        </header>
        <main className="main-content">
          {current.key === "tasks" ? (
            <TasksPage limits={system.data?.limits} />
          ) : current.key === "talents" ? (
            <TalentsPage />
          ) : current.key === "issues" ? (
            <IssuesPage />
          ) : current.key === "jobs" ? (
            <Suspense fallback={<Spin />}>
              <JobsPage />
            </Suspense>
          ) : (
            <AccountsPage />
          )}
        </main>
      </Layout>
      <Drawer
        title="系统状态"
        open={systemOpen}
        onClose={() => setSystemOpen(false)}
      >
        <ErrorPanel error={system.error} reload={system.reload} />
        <p className="muted">所有业务数据在私有环境内处理。</p>
        {system.data && (
          <>
            <Space direction="vertical" className="wide">
              {Object.entries(system.data.services).map(([key, value]) => (
                <Card size="small" key={key}>
                  <Badge
                    status={value.ok ? "success" : "error"}
                    text={`${({ postgres: "档案存储", redis: "任务调度", ollama: "本地模型", mineru: "文档解析", milvus: "人才检索" } as Record<string, string>)[key] || key}：${value.ok ? "正常" : "待恢复"}`}
                  />
                  {!value.ok && <p className="muted">{value.detail}</p>}
                </Card>
              ))}
            </Space>
            <p>
              每批最多 {system.data.limits.batch_files} 个文件，单文件上限{" "}
              {system.data.limits.file_mb} MB。
            </p>
          </>
        )}
      </Drawer>
    </Layout>
  );
}
function Login({
  onLogin,
  initialError,
}: {
  onLogin: (user: User) => void;
  initialError: string;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(initialError);
  async function login(values: { username: string; password: string }) {
    setBusy(true);
    setError("");
    try {
      const result = await api<{ user: User }>("/auth/login", {
        method: "POST",
        body: JSON.stringify(values),
      });
      onLogin(result.user);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="login-layout">
      <section className="login-story">
        <div className="brand-mark">才</div>
        <div>
          <p className="login-kicker">私有化人才管理</p>
          <h1>
            让每一份经历，
            <br />
            有据可寻。
          </h1>
          <p>
            从原始简历到结构化档案，
            <br />
            从岗位条件到逐项匹配依据。
          </p>
        </div>
        <span>人才档案工作台</span>
      </section>
      <section className="login-form">
        <div>
          <Typography.Title level={2}>登录工作台</Typography.Title>
          <p className="muted">使用管理员分配的本地账号登录。</p>
          <ErrorPanel error={error} />
          <Form layout="vertical" onFinish={login} requiredMark={false}>
            <Form.Item
              label="账号"
              name="username"
              rules={[{ required: true, message: "请输入账号" }]}
            >
              <Input autoComplete="username" autoFocus size="large" />
            </Form.Item>
            <Form.Item
              label="密码"
              name="password"
              rules={[{ required: true, message: "请输入密码" }]}
            >
              <Input.Password autoComplete="current-password" size="large" />
            </Form.Item>
            <Button
              type="primary"
              htmlType="submit"
              loading={busy}
              block
              size="large"
            >
              登录
            </Button>
          </Form>
          <Alert
            type="info"
            showIcon
            message="请勿在共享设备上保存账号密码。"
          />
        </div>
      </section>
    </div>
  );
}
