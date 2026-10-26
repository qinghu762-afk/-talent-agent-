import { useState } from "react";
import {
  App,
  Button,
  Form,
  Input,
  Modal,
  Popconfirm,
  Select,
  Space,
  Table,
  Tag,
} from "antd";
import { PlusOutlined } from "@ant-design/icons";
import { api, useResource } from "./api";
import type { User } from "./types";
import { EmptyPanel, ErrorPanel } from "./ui";
export default function AccountsPage() {
  const users = useResource<User[]>("/users");
  const [modal, setModal] = useState<"create" | User | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [form] = Form.useForm();
  const { message } = App.useApp();
  function open(value: "create" | User) {
    form.resetFields();
    form.setFieldsValue(
      value === "create" ? { role: "recruiter" } : { role: value.role },
    );
    setError("");
    setModal(value);
  }
  async function save() {
    const values = await form.validateFields();
    setSaving(true);
    setError("");
    try {
      const body =
        modal === "create"
          ? values
          : {
              role: values.role,
              ...(values.password ? { password: values.password } : {}),
            };
      await api(
        modal === "create" ? "/users" : `/users/${(modal as User).id}`,
        {
          method: modal === "create" ? "POST" : "PUT",
          body: JSON.stringify(body),
        },
      );
      message.success(modal === "create" ? "账号已创建" : "账号已更新");
      setModal(null);
      users.reload();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSaving(false);
    }
  }
  async function toggle(user: User) {
    try {
      await api(`/users/${user.id}`, {
        method: "PUT",
        body: JSON.stringify({ active: !user.active }),
      });
      message.success(user.active ? "账号已停用" : "账号已启用");
      users.reload();
    } catch (e) {
      message.error((e as Error).message);
    }
  }
  return (
    <>
      <div className="page-heading">
        <div>
          <h1>账号管理</h1>
          <p>管理本地账号与访问权限，停用账号后将无法登录。</p>
        </div>
        <Button
          type="primary"
          icon={<PlusOutlined />}
          onClick={() => open("create")}
        >
          新增账号
        </Button>
      </div>
      <section className="panel">
        <ErrorPanel error={users.error} reload={users.reload} />
        <Table
          rowKey="id"
          dataSource={users.data}
          loading={users.loading}
          locale={{ emptyText: <EmptyPanel text="暂无可显示的账号。" /> }}
          pagination={false}
          columns={[
            { title: "账号", dataIndex: "username" },
            {
              title: "角色",
              dataIndex: "role",
              render: (value) => (value === "admin" ? "管理员" : "普通用户"),
            },
            {
              title: "状态",
              dataIndex: "active",
              render: (value) => (
                <Tag color={value ? "success" : "default"}>
                  {value ? "已启用" : "已停用"}
                </Tag>
              ),
            },
            {
              title: "操作",
              render: (_, user) => (
                <Space>
                  <Button onClick={() => open(user)}>角色与密码</Button>
                  <Popconfirm
                    title={`确认${user.active ? "停用" : "启用"}账号 ${user.username}？`}
                    onConfirm={() => toggle(user)}
                  >
                    <Button danger={user.active}>
                      {user.active ? "停用" : "启用"}
                    </Button>
                  </Popconfirm>
                </Space>
              ),
            },
          ]}
        />
      </section>
      <Modal
        title={
          modal === "create"
            ? "新增本地账号"
            : `编辑账号 ${(modal as User)?.username || ""}`
        }
        open={Boolean(modal)}
        onCancel={() => setModal(null)}
        onOk={save}
        confirmLoading={saving}
        okText="保存"
        cancelText="取消"
      >
        <ErrorPanel error={error} />
        <Form layout="vertical" form={form}>
          {modal === "create" && (
            <Form.Item
              label="账号"
              name="username"
              rules={[
                { required: true, message: "请输入账号" },
                {
                  pattern: /^[a-zA-Z0-9_.-]{3,64}$/,
                  message: "使用 3–64 位字母、数字、下划线、点或短横线",
                },
              ]}
            >
              <Input autoComplete="off" />
            </Form.Item>
          )}
          <Form.Item
            label={
              modal === "create" ? "初始密码" : "新密码（留空保留现有密码）"
            }
            name="password"
            rules={[
              { required: modal === "create", message: "请输入初始密码" },
              { min: 12, message: "密码至少 12 位" },
            ]}
          >
            <Input.Password autoComplete="new-password" />
          </Form.Item>
          <Form.Item label="角色" name="role" rules={[{ required: true }]}>
            <Select
              options={[
                { value: "recruiter", label: "普通用户" },
                { value: "admin", label: "管理员" },
              ]}
            />
          </Form.Item>
          <p className="muted">
            普通用户可以管理档案与岗位；管理员还可以管理本地账号。
          </p>
        </Form>
      </Modal>
    </>
  );
}
