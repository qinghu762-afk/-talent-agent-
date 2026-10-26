import { useEffect, useState, type ReactNode } from "react";
import {
  Alert,
  App as AntApp,
  Avatar,
  Badge,
  Button,
  ConfigProvider,
  Descriptions,
  Drawer,
  Empty,
  Form,
  Input,
  Layout,
  List,
  Menu,
  Modal,
  Popconfirm,
  Radio,
  Select,
  Space,
  Spin,
  Statistic,
  Table,
  Tag,
  Typography,
  Upload,
} from "antd";
import zhCN from "antd/locale/zh_CN";
import {
  ComposeAssessment,
  CourseQuiz,
  Growth,
  JobImport,
  TalentSearch,
} from "./workflows";
import {
  BellOutlined,
  BookOutlined,
  CheckSquareOutlined,
  DashboardOutlined,
  DatabaseOutlined,
  MenuOutlined,
  MessageOutlined,
  NodeIndexOutlined,
  SettingOutlined,
  TeamOutlined,
} from "@ant-design/icons";
import {
  api,
  ApiError,
  items,
  json,
  label,
  pages,
  patch,
  post,
  visiblePages,
  taskId,
  type Role,
  type Row,
} from "./api";
import {
  AssessmentPlayer,
  Detail,
  Failure,
  ResourceTable,
  Status,
  TaskPanel,
  useResource,
} from "./components";

const roleNames: Record<Role, string> = {
  admin: "系统管理员",
  hr: "人力资源",
  manager: "部门主管",
  employee: "员工",
};
const iconFor = (group: string) =>
  ({
    工作台: <DashboardOutlined />,
    人才运营: <TeamOutlined />,
    测评与培养: <BookOutlined />,
    知识与分析: <DatabaseOutlined />,
    协作与治理: <CheckSquareOutlined />,
    平台管理: <SettingOutlined />,
  })[group];
function Login({ onLogin }: { onLogin: (user: Row) => void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>();
  return (
    <main className="login">
      <section className="login-context">
        <div className="brand">
          <span className="brand-mark">才</span>人才工作台
        </div>
        <h1>
          以真实证据，
          <br />
          连接人才与机会。
        </h1>
        <p>
          从履历、岗位到测评与培养，
          <br />
          让每一次人才决策都有据可查。
        </p>
        <div className="login-process">
          <span>人才档案</span>
          <span>岗位匹配</span>
          <span>能力培养</span>
        </div>
      </section>
      <section className="login-form">
        <Typography.Title level={2}>登录工作台</Typography.Title>
        <p className="muted">使用企业分配的账号登录</p>
        {!!error && <Failure error={error} />}
        <Form
          layout="vertical"
          onFinish={async (values) => {
            setBusy(true);
            setError(undefined);
            try {
              onLogin(await post("auth/login", values));
            } catch (e) {
              setError(e);
            } finally {
              setBusy(false);
            }
          }}
        >
          <Form.Item
            name="username"
            label="账号"
            rules={[{ required: true, message: "请输入账号" }]}
          >
            <Input size="large" autoComplete="username" />
          </Form.Item>
          <Form.Item
            name="password"
            label="密码"
            rules={[{ required: true, message: "请输入密码" }]}
          >
            <Input.Password size="large" autoComplete="current-password" />
          </Form.Item>
          <Button
            htmlType="submit"
            type="primary"
            size="large"
            block
            loading={busy}
          >
            登录工作台
          </Button>
        </Form>
        <p className="muted">账号权限决定可访问的数据与功能。</p>
      </section>
    </main>
  );
}

function ImportDialog({
  kind,
  onClose,
  onRun,
  onSaved,
}: {
  kind: "talent" | "knowledge";
  onClose: () => void;
  onRun: (id: string) => void;
  onSaved: () => void;
}) {
  const [mode, setMode] = useState("file");
  const [files, setFiles] = useState<File[]>([]);
  const [error, setError] = useState<unknown>();
  const [busy, setBusy] = useState(false);
  const [form] = Form.useForm();
  return (
    <Modal
      open
      title={kind === "talent" ? "导入人才履历" : "新增知识材料"}
      onCancel={onClose}
      okText={mode === "file" ? "上传并处理" : "保存并处理"}
      cancelText="取消"
      confirmLoading={busy}
      onOk={() => form.submit()}
      width={680}
    >
      <Form
        form={form}
        layout="vertical"
        initialValues={{ scope: "org" }}
        onFinish={async (values) => {
          setBusy(true);
          setError(undefined);
          try {
            let result: Row;
            if (mode === "file") {
              if (!files.length) throw new Error("请先选择文件");
              const body = new FormData();
              if (kind === "talent")
                files.forEach((file) => body.append("files", file));
              else {
                body.append("file", files[0]);
                body.append("title", values.title);
                body.append("scope", values.scope);
              }
              result = await api(
                kind === "talent" ? "talents/import" : "knowledge",
                { method: "POST", body },
              );
            } else
              result = await post(
                kind === "talent" ? "talents/text" : "knowledge/text",
                values,
              );
            const runId = taskId(result);
            if (runId) onRun(runId);
            onSaved();
            onClose();
          } catch (e) {
            setError(e);
          } finally {
            setBusy(false);
          }
        }}
      >
        {!!error && <Failure error={error} />}
        <Form.Item label="导入方式">
          <Radio.Group
            aria-label="导入方式"
            optionType="button"
            value={mode}
            onChange={(event) => setMode(event.target.value)}
            options={[
              { label: "文件上传", value: "file" },
              { label: "粘贴文本", value: "text" },
            ]}
          />
        </Form.Item>
        {kind === "knowledge" && (
          <>
            <Form.Item
              label="标题"
              name="title"
              rules={[{ required: true, message: "请填写标题" }]}
            >
              <Input />
            </Form.Item>
            <Form.Item label="可见范围" name="scope">
              <Select
                options={[
                  { label: "所属组织", value: "org" },
                  { label: "仅自己", value: "private" },
                  { label: "全公司（需要权限）", value: "company" },
                ]}
              />
            </Form.Item>
          </>
        )}
        {mode === "file" ? (
          <Form.Item
            label={kind === "talent" ? "履历文件（可多选）" : "知识文件"}
            extra="支持PDF、Word、Excel、PPT、图片、TXT、Markdown、HTML；文件由后端校验与解析。"
          >
            <Upload.Dragger
              multiple={kind === "talent"}
              maxCount={kind === "knowledge" ? 1 : undefined}
              accept=".pdf,.doc,.docx,.xls,.xlsx,.ppt,.pptx,.png,.jpg,.jpeg,.webp,.txt,.md,.html,.htm,.csv"
              beforeUpload={() => false}
              fileList={files.map((file, i) => ({
                uid: String(i),
                name: file.name,
                originFileObj: file as any,
              }))}
              onChange={({ fileList }) =>
                setFiles(
                  fileList
                    .map((file) => file.originFileObj as File)
                    .filter(Boolean),
                )
              }
            >
              <p>点击选择或拖入文件</p>
              <p className="muted">解析完成后请核对原文证据与异常提示</p>
            </Upload.Dragger>
          </Form.Item>
        ) : (
          <Form.Item
            label={kind === "talent" ? "履历全文" : "知识正文"}
            name="text"
            rules={[{ required: true, message: "请填写正文" }]}
          >
            <Input.TextArea rows={12} />
          </Form.Item>
        )}
      </Form>
    </Modal>
  );
}

function Dashboard({
  user,
  navigate,
}: {
  user: Row;
  navigate: (key: string) => void;
}) {
  const { data, error, loading, reload } = useResource("dashboard");
  if (error) return <Failure error={error} retry={reload} />;
  if (loading) return <Spin />;
  const counts = data?.counts || data || {};
  const keys =
    user.role === "employee"
      ? [
          ["assessments", "待完成测评", "assessments"],
          ["training", "培训计划", "learning"],
          ["runs", "后台任务", "runs"],
        ]
      : [
          ["talents", "人才档案", "talents"],
          ["jobs", "开放岗位", "jobs"],
          ["assessments", "测评", "assessments"],
          ["training", "培养计划", "learning"],
        ];
  return (
    <>
      <section className="overview-intro">
        <div>
          <h2>
            {user.role === "employee"
              ? "今天，继续你的成长计划"
              : "让人才决策，回到证据本身"}
          </h2>
          <p>通过下方工作入口继续处理；数据仅展示当前账号可访问的范围。</p>
        </div>
        <Button
          type="primary"
          onClick={() =>
            navigate(user.role === "employee" ? "learning" : "talents")
          }
        >
          {user.role === "employee" ? "进入我的学习" : "管理人才档案"}
        </Button>
      </section>
      <div className="metrics">
        {keys.map(([key, title, page]) => (
          <button key={key} onClick={() => navigate(page)}>
            <Statistic
              title={title}
              value={
                typeof counts[key] === "number"
                  ? counts[key]
                  : (counts[key]?.total ?? "—")
              }
            />
            <span className="muted">查看详情</span>
          </button>
        ))}
      </div>
      <div className="overview-columns">
        <section className="surface">
          <h3>下一步工作</h3>
          <List
            dataSource={
              user.role === "employee"
                ? [
                    [
                      "完成分配的能力测评",
                      "测评记录与结果可在个人账号查看",
                      "assessments",
                    ],
                    ["继续课程学习", "保存学习位置，推进培训计划", "learning"],
                    ["查询工作知识", "核对引用，了解回答的依据", "chat"],
                  ]
                : [
                    [
                      "完善人才档案",
                      "导入履历后核对教育、经历与原文证据",
                      "talents",
                    ],
                    [
                      "运行岗位匹配",
                      "先定义必要条件，再查看评分和差距",
                      "jobs",
                    ],
                    [
                      "推进测评审批",
                      "确认题目和参测对象，批准后开始答题",
                      "approvals",
                    ],
                  ]
            }
            renderItem={(row) => (
              <List.Item
                actions={[
                  <Button onClick={() => navigate(row[2])}>进入</Button>,
                ]}
              >
                <List.Item.Meta title={row[0]} description={row[1]} />
              </List.Item>
            )}
          />
        </section>
        <section className="surface">
          <h3>工作流</h3>
          <ol className="workflow">
            <li>
              <strong>采集与核对</strong>
              <p>履历解析、版本追踪与知识入库</p>
            </li>
            <li>
              <strong>评估与决策</strong>
              <p>岗位条件、能力评分与可验证证据</p>
            </li>
            <li>
              <strong>学习与反馈</strong>
              <p>审批、测评结果和培养计划形成闭环</p>
            </li>
          </ol>
          <Alert
            type="info"
            showIcon
            message="模型结论是辅助判断，请结合业务证据复核。"
          />
        </section>
      </div>
    </>
  );
}

function TalentDetail({
  id,
  onClose,
  onSaved,
}: {
  id: string;
  onClose: () => void;
  onSaved: () => void;
}) {
  const { data, error, loading, reload } = useResource(`talents/${id}`);
  const [undoError, setUndoError] = useState<unknown>();
  return (
    <Drawer
      open
      title={data?.profile?.name || "人才档案"}
      onClose={onClose}
      width={820}
    >
      {error ? (
        <Failure error={error} retry={reload} />
      ) : loading ? (
        <Spin />
      ) : (
        <>
          <Space>
            <Tag>档案版本 {data.revision}</Tag>
            <Tag>索引版本 {data.indexed_revision ?? "尚未索引"}</Tag>
          </Space>
          {data.indexed_revision !== data.revision && (
            <Alert
              type="warning"
              message="索引与当前档案版本不同，匹配结果需关注版本信息。"
            />
          )}
          <h3>人才画像</h3>
          <Detail value={data.profile} />
          <Growth id={id} />
          <h3>文档与来源</h3>
          <List
            dataSource={data.documents || []}
            locale={{ emptyText: "暂无原始文档" }}
            renderItem={(document: Row) => (
              <List.Item>
                <Space wrap>
                  <span>
                    {document.name || document.filename || document.id}
                  </span>
                  <a
                    href={`/api/v1/documents/${document.id}/file`}
                    target="_blank"
                    rel="noreferrer"
                  >
                    查看原始文件
                  </a>
                </Space>
              </List.Item>
            )}
          />
          <details>
            <summary>修订历史</summary>
            <Detail value={data.revisions} />
          </details>
          <h3>合并记录</h3>
          {!!undoError && <Failure error={undoError} />}
          <List
            dataSource={data.merges || []}
            locale={{ emptyText: "暂无合并记录" }}
            renderItem={(merge: Row) => (
              <List.Item
                actions={
                  merge.undone
                    ? []
                    : [
                        <Popconfirm
                          title="撤销此合并并恢复对应档案？"
                          onConfirm={async () => {
                            try {
                              await post(`merges/${merge.id}/undo`);
                              void reload();
                              onSaved();
                            } catch (e) {
                              setUndoError(e);
                            }
                          }}
                        >
                          <Button danger>撤销合并</Button>
                        </Popconfirm>,
                      ]
                }
              >
                <Detail value={merge} />
              </List.Item>
            )}
          />
        </>
      )}
    </Drawer>
  );
}

function Learning({ user, onRun }: { user: Row; onRun: (id: string) => void }) {
  const courses = useResource("courses");
  const [plan, setPlan] = useState<Row>();
  const [course, setCourse] = useState<Row>();
  const [position, setPosition] = useState(0);
  const [error, setError] = useState<unknown>();
  const [recommend, setRecommend] = useState(false);
  const [refresh, setRefresh] = useState(0);
  const { message } = AntApp.useApp();
  return (
    <>
      <ResourceTable
        resource="training-plans"
        editable={["admin", "hr"].includes(user.role)}
        refresh={refresh}
        toolbar={
          user.role !== "employee" && (
            <Button onClick={() => setRecommend(true)}>生成培养建议</Button>
          )
        }
        onSelect={async (row) => {
          try {
            setPlan(await api(`training-plans/${row.id}`));
          } catch (e) {
            setError(e);
          }
        }}
        actions={(row) => (
          <Button
            size="small"
            onClick={async () => {
              try {
                setPlan(await api(`training-plans/${row.id}`));
              } catch (e) {
                setError(e);
              }
            }}
          >
            进入学习
          </Button>
        )}
      />
      {!!error && <Failure error={error} />}
      <Drawer
        title={plan?.title || "培训计划"}
        open={!!plan}
        width={760}
        onClose={() => {
          setPlan(undefined);
          setCourse(undefined);
        }}
      >
        {plan && (
          <>
            <Status value={plan.status} />
            <List
              dataSource={
                plan.courses ||
                (plan.course_ids || []).map((id: string) => ({ id }))
              }
              locale={{ emptyText: "计划中暂无课程" }}
              renderItem={(row: Row) => (
                <List.Item
                  actions={[
                    <Button
                      onClick={async () => {
                        try {
                          const loaded = await api(`courses/${row.id}`);
                          setCourse(loaded);
                          const progress = plan.progress?.[row.id];
                          setPosition(
                            typeof progress === "number"
                              ? progress
                              : progress?.position_seconds || 0,
                          );
                        } catch (e) {
                          setError(e);
                        }
                      }}
                    >
                      学习课程
                    </Button>,
                  ]}
                >
                  {row.title ||
                    items(courses.data).find((item) => item.id === row.id)
                      ?.title ||
                    row.id}
                </List.Item>
              )}
            />
            {course && (
              <section className="course-content">
                <h3>{course.title}</h3>
                <div className="preserve">{course.content}</div>
                <Form
                  layout="vertical"
                  onFinish={async () => {
                    try {
                      const saved = await post(
                        `training-plans/${plan.id}/progress`,
                        {
                          course_id: course.id,
                          position_seconds: position,
                        },
                      );
                      const actual = saved.progress?.[course.id];
                      if (actual?.position_seconds < position)
                        message.warning(
                          "进度超过实际学习时间，已按有效学习时长保存",
                        );
                      else message.success("学习进度已保存");
                      setRefresh((value) => value + 1);
                      setPlan(await api(`training-plans/${plan.id}`));
                    } catch (e) {
                      setError(e);
                    }
                  }}
                >
                  <Form.Item
                    label={`学习位置（秒），课程时长 ${course.duration_seconds || 0} 秒`}
                  >
                    <Input
                      type="number"
                      min={0}
                      max={course.duration_seconds || undefined}
                      value={position}
                      onChange={(event) =>
                        setPosition(Number(event.target.value))
                      }
                    />
                  </Form.Item>
                  <Button type="primary" htmlType="submit">
                    保存学习进度
                  </Button>
                  <Button
                    onClick={() => setPosition(course.duration_seconds || 0)}
                  >
                    标记已学到结尾
                  </Button>
                </Form>
                <CourseQuiz
                  key={course.id}
                  plan={plan}
                  course={course}
                  onSaved={() => {
                    void api(`training-plans/${plan.id}`)
                      .then(setPlan)
                      .catch(setError);
                  }}
                />
              </section>
            )}
            {!!error && <Failure error={error} />}
          </>
        )}
      </Drawer>
      {recommend && (
        <RecommendModal onClose={() => setRecommend(false)} onRun={onRun} />
      )}
    </>
  );
}
function RecommendModal({
  onClose,
  onRun,
}: {
  onClose: () => void;
  onRun: (id: string) => void;
}) {
  const talents = useResource("talents");
  const assessments = useResource("assessments");
  const [error, setError] = useState<unknown>();
  const [busy, setBusy] = useState(false);
  const [form] = Form.useForm();
  return (
    <Modal
      open
      title="生成培养建议"
      onCancel={onClose}
      okText="生成建议"
      cancelText="取消"
      confirmLoading={busy}
      onOk={() => form.submit()}
    >
      <p>根据人才画像、测评差距和现有课程生成培养建议。</p>
      {!!error && <Failure error={error} />}
      <Form
        form={form}
        layout="vertical"
        onFinish={async (values) => {
          setBusy(true);
          try {
            const run = await post("training-plans/recommend", values);
            onRun(run.id);
            onClose();
          } catch (e) {
            setError(e);
          } finally {
            setBusy(false);
          }
        }}
      >
        <Form.Item
          name="talent_id"
          label="参训人才"
          rules={[{ required: true, message: "请选择人才" }]}
        >
          <Select
            showSearch
            optionFilterProp="label"
            options={items(talents.data).map((row) => ({
              label: label(row),
              value: row.id,
            }))}
          />
        </Form.Item>
        <Form.Item name="assessment_id" label="参考测评（可选）">
          <Select
            allowClear
            options={items(assessments.data).map((row) => ({
              label: label(row),
              value: row.id,
            }))}
          />
        </Form.Item>
      </Form>
    </Modal>
  );
}

function Conversation({
  kind,
  onRun,
}: {
  kind: "chat" | "analysis";
  onRun: (id: string) => void;
}) {
  const [question, setQuestion] = useState("");
  const [datasource, setDatasource] = useState("postgres");
  const [session, setSession] = useState<string>();
  const [followup, setFollowup] = useState(false);
  const [history, setHistory] = useState<{ question: string; id: string }[]>(
    [],
  );
  const [error, setError] = useState<unknown>();
  const [busy, setBusy] = useState(false);
  return (
    <section className="conversation">
      <div className="conversation-intro">
        {kind === "chat" ? <MessageOutlined /> : <DatabaseOutlined />}
        <h2>
          {kind === "chat"
            ? "从工作知识中，找到可靠答案"
            : "向授权数据提出一个具体问题"}
        </h2>
        <p className="muted">
          {kind === "chat"
            ? "回答将附上引用来源，知识库中没有依据时请先补充材料。"
            : "结果包含查询SQL、数据明细与图表，可导出Word和PDF报告。"}
        </p>
      </div>
      {history.map((entry) => (
        <section key={entry.id} className="conversation-entry">
          <h3>{entry.question}</h3>
          <TaskPanel
            id={entry.id}
            onComplete={(run) => {
              if (run?.result?.session_id) setSession(run.result.session_id);
              setFollowup(!!run?.result?.needs_clarification);
            }}
          />
        </section>
      ))}
      {!!error && <Failure error={error} />}
      <Form
        onFinish={async () => {
          if (!question.trim()) return;
          setBusy(true);
          setError(undefined);
          try {
            const run = await post(kind, {
              question,
              session_id: session,
              ...(kind === "analysis" ? { datasource } : {}),
            });
            setHistory((value) => [...value, { question, id: run.id }]);
            setFollowup(false);
            setQuestion("");
          } catch (e) {
            setError(e);
          } finally {
            setBusy(false);
          }
        }}
      >
        <Form.Item>
          <Input.TextArea
            aria-label={kind === "chat" ? "知识问题" : "数据问题"}
            placeholder={
              followup
                ? "请补充上方追问，继续本次分析"
                : kind === "chat"
                  ? "输入需要了解的制度、岗位或培训问题"
                  : "例如：按组织统计当前人才技能覆盖情况"
            }
            value={question}
            onChange={(event) => setQuestion(event.target.value)}
            rows={3}
            maxLength={10000}
            showCount
          />
        </Form.Item>
        <div className="row">
          {kind === "analysis" && (
            <Select
              aria-label="数据源"
              value={datasource}
              onChange={setDatasource}
              options={[
                { label: "PostgreSQL 分析库", value: "postgres" },
                { label: "MySQL 业务只读视图", value: "mysql" },
              ]}
            />
          )}
          <Button
            type="primary"
            htmlType="submit"
            loading={busy}
            disabled={!question.trim()}
          >
            {" "}
            {followup
              ? "补充并继续分析"
              : kind === "chat"
                ? "发送问题"
                : "分析数据"}{" "}
          </Button>
          <Button
            disabled={!history.length}
            onClick={() => {
              setHistory([]);
              setSession(undefined);
              setFollowup(false);
            }}
          >
            新建会话
          </Button>
          {history.length > 0 && (
            <Button onClick={() => onRun(history[history.length - 1].id)}>
              在任务中心查看
            </Button>
          )}
        </div>
      </Form>
    </section>
  );
}

function Approval({ row, onSaved }: { row: Row; onSaved: () => void }) {
  const [open, setOpen] = useState(false);
  const [comment, setComment] = useState("");
  const [error, setError] = useState<unknown>();
  const [busy, setBusy] = useState(false);
  const resolve = async (approved: boolean) => {
    setBusy(true);
    try {
      await post(`approvals/${row.id}/resolve`, { approved, comment });
      onSaved();
      setOpen(false);
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  };
  return (
    <>
      <Button
        size="small"
        disabled={row.status !== "pending"}
        onClick={() => setOpen(true)}
      >
        审批
      </Button>
      <Modal
        open={open}
        onCancel={() => setOpen(false)}
        title={
          row.kind === "assessment_rating" ? "审批测评级定" : "审批测评发布"
        }
        footer={
          <Space>
            <Button onClick={() => setOpen(false)}>取消</Button>
            <Button danger loading={busy} onClick={() => resolve(false)}>
              驳回
            </Button>
            <Button type="primary" loading={busy} onClick={() => resolve(true)}>
              {row.kind === "assessment_rating" ? "批准评级" : "批准发布"}
            </Button>
          </Space>
        }
      >
        <Detail value={row} />
        <Form layout="vertical">
          <Form.Item label="审批意见">
            <Input.TextArea
              value={comment}
              onChange={(event) => setComment(event.target.value)}
              rows={3}
            />
          </Form.Item>
        </Form>
        {!!error && <Failure error={error} />}
      </Modal>
    </>
  );
}

function SkillExecute({
  row,
  onRun,
}: {
  row: Row;
  onRun: (id: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [parameters, setParameters] = useState("{}");
  const [error, setError] = useState<unknown>();
  return (
    <>
      <Button
        size="small"
        disabled={!row.enabled}
        onClick={() => setOpen(true)}
      >
        运行
      </Button>
      <Modal
        open={open}
        title={`运行 ${row.name}`}
        onCancel={() => setOpen(false)}
        okText="运行"
        cancelText="取消"
        onOk={async () => {
          try {
            const run = await post(`skills/${row.id}/execute`, {
              parameters: JSON.parse(parameters),
            });
            onRun(run.id);
            setOpen(false);
          } catch (e) {
            setError(e);
          }
        }}
      >
        <details>
          <summary>输入结构</summary>
          <pre>{json(row.input_schema)}</pre>
        </details>
        <Form layout="vertical">
          <Form.Item label="执行参数（JSON）">
            <Input.TextArea
              rows={8}
              value={parameters}
              onChange={(event) => setParameters(event.target.value)}
            />
          </Form.Item>
        </Form>
        {!!error && <Failure error={error} />}
      </Modal>
    </>
  );
}

function Workspace({ user, onLogout }: { user: Row; onLogout: () => void }) {
  const initial = location.hash.slice(1) || "dashboard";
  const [page, setPage] = useState(initial);
  const [mobile, setMobile] = useState(false);
  const [runId, setRunId] = useState<string>();
  const [talent, setTalent] = useState<string>();
  const [knowledge, setKnowledge] = useState<Row>();
  const [exam, setExam] = useState<Row>();
  const [compose, setCompose] = useState(false);
  const [jobImport, setJobImport] = useState(false);
  const [importKind, setImportKind] = useState<"talent" | "knowledge">();
  const [refresh, setRefresh] = useState(0);
  const [error, setError] = useState<unknown>();
  const { message } = AntApp.useApp();
  const allowed = visiblePages(user.role);
  const navigate = (key: string) => {
    setPage(key);
    location.hash = key;
    setMobile(false);
    setError(undefined);
  };
  useEffect(() => {
    const handle = () => {
      setPage(location.hash.slice(1) || "dashboard");
      setError(undefined);
    };
    window.addEventListener("hashchange", handle);
    return () => window.removeEventListener("hashchange", handle);
  }, []);
  const action = async (path: string, data: Row = {}, reload?: () => void) => {
    setError(undefined);
    try {
      const result = await post(path, data);
      if (path.endsWith("/match") || path.endsWith("/execute"))
        setRunId(result.id);
      else message.success("操作已完成");
      reload?.();
      setRefresh((value) => value + 1);
    } catch (e) {
      setError(e);
    }
  };
  const grouped = [...new Set(allowed.map((key) => pages[key].group))].map(
    (group) => ({
      type: "group" as const,
      label: group,
      children: allowed
        .filter((key) => pages[key].group === group)
        .map((key) => ({ key, label: pages[key].title, icon: iconFor(group) })),
    }),
  );
  const menu = (
    <>
      <div className="brand">
        <span className="brand-mark">才</span>
        <span>
          人才工作台<small>企业人才与成长平台</small>
        </span>
      </div>
      <Menu
        mode="inline"
        selectedKeys={[page]}
        items={grouped}
        onClick={({ key }) => navigate(key)}
      />
      <div className="sidebar-note">
        <NodeIndexOutlined /> 基于证据的评估与培养
      </div>
    </>
  );
  let content: ReactNode;
  if (!allowed.includes(page))
    content = (
      <Alert
        type="error"
        message="无权访问此页面"
        description="当前账号没有此功能权限，可从左侧选择已授权的工作入口。"
      />
    );
  else if (page === "dashboard")
    content = <Dashboard user={user} navigate={navigate} />;
  else if (page === "talents")
    content = (
      <>
        <TalentSearch onRun={setRunId} />
        <ResourceTable
          resource="talents"
          refresh={refresh}
          editable={["admin", "hr"].includes(user.role)}
          toolbar={
            <Button onClick={() => setImportKind("talent")}>导入履历</Button>
          }
          onSelect={(row) => setTalent(row.id)}
        />
      </>
    );
  else if (page === "jobs")
    content = (
      <ResourceTable
        resource="jobs"
        refresh={refresh}
        editable={["admin", "hr"].includes(user.role)}
        toolbar={
          ["admin", "hr"].includes(user.role) && (
            <Button onClick={() => setJobImport(true)}>导入岗位文件</Button>
          )
        }
        actions={(row, reload) => (
          <Button
            size="small"
            type="primary"
            onClick={() => action(`jobs/${row.id}/match`, {}, reload)}
          >
            运行匹配
          </Button>
        )}
      />
    );
  else if (page === "assessments")
    content = (
      <ResourceTable
        resource="assessments"
        refresh={refresh}
        editable={["admin", "hr"].includes(user.role)}
        toolbar={
          ["admin", "hr"].includes(user.role) && (
            <Button onClick={() => setCompose(true)}>自动组卷</Button>
          )
        }
        onSelect={setExam}
        actions={(row, reload) => (
          <>
            {["admin", "hr"].includes(user.role) && (
              <Button
                size="small"
                onClick={() =>
                  action(`assessments/${row.id}/retest`, {}, reload)
                }
              >
                创建复测
              </Button>
            )}
            {["admin", "hr"].includes(user.role) &&
              ["draft", "rejected"].includes(row.status) && (
                <Button
                  size="small"
                  onClick={() =>
                    action(`assessments/${row.id}/publish`, {}, reload)
                  }
                >
                  提交发布审批
                </Button>
              )}
            <Button size="small" onClick={() => setExam(row)}>
              {["published", "approved", "in_progress", "started"].includes(
                row.status,
              )
                ? "进入测评"
                : "详情与结果"}
            </Button>
          </>
        )}
      />
    );
  else if (page === "learning")
    content = <Learning user={user} onRun={setRunId} />;
  else if (page === "chat" || page === "analysis")
    content = <Conversation key={page} kind={page} onRun={setRunId} />;
  else if (page === "knowledge")
    content = (
      <ResourceTable
        resource="knowledge"
        refresh={refresh}
        editable={["admin", "hr"].includes(user.role)}
        toolbar={
          ["admin", "hr"].includes(user.role) && (
            <Button type="primary" onClick={() => setImportKind("knowledge")}>
              新增知识材料
            </Button>
          )
        }
        onSelect={async (row) => {
          try {
            setKnowledge(await api(`knowledge/${row.id}`));
          } catch (e) {
            setError(e);
          }
        }}
      />
    );
  else if (page === "approvals")
    content = (
      <ResourceTable
        resource="approvals"
        actions={(row, reload) => <Approval row={row} onSaved={reload} />}
      />
    );
  else if (page === "runs")
    content = (
      <ResourceTable
        resource="runs"
        refresh={refresh}
        onSelect={(row) => setRunId(row.id)}
        actions={(row) => (
          <Button size="small" onClick={() => setRunId(row.id)}>
            查看进度与结果
          </Button>
        )}
      />
    );
  else if (page === "notifications")
    content = (
      <ResourceTable
        resource="notifications"
        actions={(row, reload) =>
          !row.read && (
            <Button
              size="small"
              onClick={async () => {
                try {
                  await patch(`notifications/${row.id}`, { read: true });
                  void reload();
                } catch (e) {
                  setError(e);
                }
              }}
            >
              标记已读
            </Button>
          )
        }
      />
    );
  else if (page === "skills")
    content = (
      <ResourceTable
        resource="skills"
        actions={(row) => <SkillExecute row={row} onRun={setRunId} />}
      />
    );
  else if (page === "users")
    content = (
      <>
        <h2 className="subheading">企业账号</h2>
        <ResourceTable resource="users" />
        <h2 className="subheading">组织架构</h2>
        <ResourceTable resource="organizations" />
        <h2 className="subheading">角色与权限模板</h2>
        <Alert
          type="info"
          showIcon
          message="模板用于收紧基础角色的操作范围、数据范围和可见字段；不能扩大基础角色已有权限。"
        />
        <ResourceTable resource="roles" />
      </>
    );
  else if (page === "system") content = <System />;
  else
    content = (
      <ResourceTable
        key={page}
        resource={page}
        editable={user.role === "admin" || user.role === "hr"}
      />
    );
  return (
    <Layout className="app-layout">
      <Layout.Sider width={230} className="desktop-sidebar" theme="light">
        {menu}
      </Layout.Sider>
      <Drawer
        placement="left"
        open={mobile}
        onClose={() => setMobile(false)}
        width={270}
        className="mobile-menu"
      >
        {menu}
      </Drawer>
      <Layout>
        <header className="topbar">
          <Space>
            <Button
              className="mobile-toggle"
              icon={<MenuOutlined />}
              aria-label="打开导航"
              onClick={() => setMobile(true)}
            />
            <span className="topbar-organization">企业人才管理</span>
            <span className="muted desktop-only">/</span>
            <span className="desktop-only">
              {pages[page]?.title || "访问受限"}
            </span>
          </Space>
          <Space size="middle">
            <Button
              type="text"
              aria-label="查看通知"
              icon={<BellOutlined />}
              onClick={() => navigate("notifications")}
            />
            <Avatar
              size="small"
              style={{ background: "#e7eef3", color: "#195b82" }}
            >
              {user.username?.slice(0, 1)}
            </Avatar>
            <span className="username">{user.username}</span>
            <Tag className="role-tag">{roleNames[user.role as Role]}</Tag>
            <Button
              size="small"
              onClick={async () => {
                try {
                  await post("auth/logout");
                  onLogout();
                } catch (e) {
                  setError(e);
                }
              }}
            >
              退出
            </Button>
          </Space>
        </header>
        <main className="main-content">
          <div className="page-heading">
            <h1>{pages[page]?.title || "访问受限"}</h1>
            <p>{pages[page]?.hint}</p>
          </div>
          {!!error && (
            <div className="page-error">
              <Failure error={error} />
            </div>
          )}
          <div className="page-content" key={page}>
            {content}
          </div>
          <footer>企业 AI 人才平台 · 数据权限由服务端校验</footer>
        </main>
      </Layout>
      <Drawer
        open={!!runId}
        title="任务进度与结果"
        width={900}
        onClose={() => setRunId(undefined)}
        destroyOnClose
      >
        {runId && (
          <TaskPanel
            id={runId}
            onComplete={() => setRefresh((value) => value + 1)}
          />
        )}
      </Drawer>
      {talent && (
        <TalentDetail
          id={talent}
          onClose={() => setTalent(undefined)}
          onSaved={() => setRefresh((value) => value + 1)}
        />
      )}
      <Drawer
        open={!!knowledge}
        title={knowledge?.title || "知识详情"}
        width={760}
        onClose={() => setKnowledge(undefined)}
      >
        <Detail value={knowledge} />
      </Drawer>
      {compose && (
        <ComposeAssessment
          onClose={() => setCompose(false)}
          onSaved={() => setRefresh((value) => value + 1)}
        />
      )}
      {jobImport && (
        <JobImport onClose={() => setJobImport(false)} onRun={setRunId} />
      )}
      {exam && (
        <AssessmentPlayer
          record={exam}
          onClose={() => {
            setExam(undefined);
            setRefresh((value) => value + 1);
          }}
          onRun={setRunId}
        />
      )}
      {importKind && (
        <ImportDialog
          kind={importKind}
          onClose={() => setImportKind(undefined)}
          onRun={setRunId}
          onSaved={() => setRefresh((value) => value + 1)}
        />
      )}
    </Layout>
  );
}
function System() {
  const { data, error, loading, reload } = useResource("system");
  return error ? (
    <Failure error={error} retry={reload} />
  ) : loading ? (
    <Spin />
  ) : (
    <>
      <Alert
        type="info"
        message="此处显示后端实时状态，模型与服务异常会影响相关任务。"
      />
      <Detail value={data} />
      {data?.dify_url && (
        <a href={data.dify_url} target="_blank" rel="noreferrer">
          打开 Dify 管理台
        </a>
      )}
    </>
  );
}
function AuthenticatedApp() {
  const [user, setUser] = useState<Row | null>();
  const [error, setError] = useState<unknown>();
  const load = async () => {
    setError(undefined);
    try {
      setUser(await api("auth/me"));
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) setUser(null);
      else setError(e);
    }
  };
  useEffect(() => {
    void load();
  }, []);
  if (error)
    return (
      <div className="bootstrap">
        <Failure error={error} retry={load} />
      </div>
    );
  if (user === undefined)
    return (
      <div className="bootstrap">
        <Spin tip="正在连接工作台">
          <div style={{ height: 100 }} />
        </Spin>
      </div>
    );
  return user ? (
    <Workspace user={user} onLogout={() => setUser(null)} />
  ) : (
    <Login onLogin={setUser} />
  );
}
export default function App() {
  return (
    <ConfigProvider
      locale={zhCN}
      theme={{
        token: {
          colorPrimary: "#195b82",
          colorSuccess: "#16756c",
          colorInfo: "#195b82",
          colorWarning: "#9a641b",
          colorError: "#b33e43",
          colorText: "#233544",
          colorTextSecondary: "#566878",
          colorBorder: "#ccd6df",
          borderRadius: 6,
          fontFamily:
            '"Microsoft YaHei UI", "PingFang SC", "Noto Sans SC", sans-serif',
          fontSize: 14,
        },
        components: {
          Menu: { itemHeight: 39, itemSelectedBg: "#e9f0f5" },
          Button: { controlHeight: 34 },
          Table: { headerBg: "#edf2f6" },
        },
      }}
    >
      <AntApp>
        <AuthenticatedApp />
      </AntApp>
    </ConfigProvider>
  );
}
