import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import {
  Alert,
  App as AntApp,
  Button,
  Checkbox,
  Descriptions,
  Drawer,
  Empty,
  Form,
  Input,
  InputNumber,
  List,
  Modal,
  Popconfirm,
  Progress,
  Radio,
  Select,
  Space,
  Spin,
  Table,
  Tag,
  Typography,
} from "antd";
import {
  api,
  ApiError,
  items,
  json,
  label,
  patch,
  post,
  statusNames,
  chartOption,
  deadlineRemaining,
  type Row,
} from "./api";
import { schemas, type Field } from "./catalog";
import {
  analysisData,
  analysisOption,
  chartTypes,
  type AnalysisChartType,
} from "./analysis-chart";

export function Failure({
  error,
  retry,
}: {
  error: unknown;
  retry?: () => void;
}) {
  const e = error as ApiError;
  return (
    <Alert
      type="error"
      showIcon
      message={e?.status === 403 ? "无权执行此操作" : e?.message || "操作失败"}
      description={
        <Space wrap>
          {e?.status === 403 && (
            <span>{e.message}，请联系管理员调整权限。</span>
          )}
          {e?.requestId && <span>请求编号：{e.requestId}</span>}
          {retry && <Button onClick={retry}>重试</Button>}
        </Space>
      }
    />
  );
}
export function Status({ value }: { value: any }) {
  const color = ["failed", "rejected"].includes(value)
    ? "error"
    : ["completed", "succeeded", "approved", "ready"].includes(value)
      ? "success"
      : ["running", "in_progress", "indexing"].includes(value)
        ? "processing"
        : "default";
  return (
    <Tag color={color}>{statusNames[value] || String(value ?? "未设置")}</Tag>
  );
}
export function useResource(path: string) {
  const [data, setData] = useState<any>();
  const [error, setError] = useState<unknown>();
  const [loading, setLoading] = useState(true);
  const reload = useCallback(async () => {
    setLoading(true);
    setError(undefined);
    try {
      setData(await api(path));
    } catch (e) {
      setError(e);
    } finally {
      setLoading(false);
    }
  }, [path]);
  useEffect(() => {
    void reload();
  }, [reload]);
  return { data, error, loading, reload };
}
export function Detail({ value }: { value: any }) {
  if (value == null) return <span className="muted">未提供</span>;
  if (typeof value !== "object")
    return <span className="preserve">{String(value)}</span>;
  if (Array.isArray(value)) {
    if (!value.length) return <span className="muted">暂无记录</span>;
    return (
      <div className="detail-list">
        {value.map((entry, i) => (
          <div key={i}>
            <Detail value={entry} />
          </div>
        ))}
      </div>
    );
  }
  const names: Record<string, string> = {
    id: "编号",
    profile: "人才画像",
    name: "姓名",
    skills: "技能",
    education: "教育经历",
    experiences: "工作经历",
    projects: "项目经历",
    certificates: "证书",
    intentions: "求职意向",
    evidence: "原文证据",
    summary: "摘要",
    tags: "标签",
    anomalies: "异常提示",
    experience_months: "工作月数",
    completeness: "完整度",
    revision: "当前版本",
    indexed_revision: "索引版本",
    documents: "原始文档",
    revisions: "版本历史",
    merges: "合并历史",
    email: "邮箱",
    phone: "电话",
    location: "地点",
    requirements: "岗位要求",
    required_skills: "必要技能",
    preferred_skills: "加分技能",
    min_education: "最低学历",
    min_experience_months: "最低工作月数",
    required_certificates: "必要证书",
    responsibilities: "职责",
    conditions: "条件检查",
    strengths: "优势",
    gaps: "差距",
    unknowns: "待核实",
    eligible: "满足必要条件",
    total: "总分",
    dimensions: "评分维度",
    diagnostics: "诊断信息",
    versions: "模型与版本",
    source_id: "来源编号",
    source_path: "来源路径",
    chunk: "原文分块",
    quote: "引用原文",
    feedback: "反馈建议",
    risks: "风险提示",
    inference: "模型推断",
    status: "状态",
    progress: "进度",
    error: "错误",
    title: "标题",
    content: "内容",
    result: "结果",
    created_at: "创建时间",
    updated_at: "更新时间",
    kind: "类型",
    org_id: "组织",
    owner_id: "所有者",
    action: "操作",
    actor_id: "操作者",
    resource: "资源",
    resource_id: "资源编号",
    details: "详情",
    reasons: "推荐原因",
    course_ids: "课程编号",
    talent_id: "人才编号",
    assessment_id: "测评编号",
    position_seconds: "学习位置（秒）",
    scope: "可见范围",
    text: "正文",
    read: "已读",
    score: "评分",
    company: "公司",
    role: "职位",
    school: "学校",
    degree: "学历",
    start: "起始",
    end: "结束",
    field: "字段",
    value: "值",
  };
  return (
    <Descriptions
      size="small"
      column={1}
      bordered
      items={Object.entries(value).map(([key, v]) => ({
        key,
        label: names[key] || key,
        children:
          typeof v === "boolean" ? v ? "是" : "否" : <Detail value={v} />,
      }))}
    />
  );
}
export function Chart({
  option,
  label: caption,
  theme = "light",
  height,
}: {
  option: Row;
  label: string;
  theme?: "light" | "dark";
  height?: number;
}) {
  const node = useRef<HTMLDivElement>(null);
  useEffect(() => {
    let dispose: (() => void) | undefined;
    let cancelled = false;
    void import("echarts").then(({ init }) => {
      if (cancelled || !node.current) return;
      const chart = init(node.current, theme === "dark" ? "dark" : undefined);
      chart.setOption({
        ...option,
        color:
          theme === "dark"
            ? ["#8fc1df", "#7fcbbd", "#b0bfcd", "#dfb978", "#c3acd6"]
            : ["#195b82", "#16756c", "#677c91", "#b37525", "#8b6f9e"],
        backgroundColor: theme === "dark" ? "#172638" : "#ffffff",
      });
      const resize = () => chart.resize();
      const observer = new ResizeObserver(resize);
      observer.observe(node.current);
      dispose = () => {
        observer.disconnect();
        chart.dispose();
      };
    });
    return () => {
      cancelled = true;
      dispose?.();
    };
  }, [option, theme, height]);
  return (
    <div>
      <div
        role="img"
        aria-label={caption}
        ref={node}
        className="chart"
        style={height ? { height } : undefined}
      />
      <p className="muted chart-caption">{caption}</p>
    </div>
  );
}
export function AnalysisChart({ result }: { result: Row }) {
  const data = analysisData(result);
  const [type, setType] = useState<AnalysisChartType>("bar");
  const [dimension, setDimension] = useState(
    data.categories[0] || data.columns[0] || "",
  );
  const [metrics, setMetrics] = useState<string[]>(
    data.numeric.filter((key) => key !== dimension).slice(0, 1),
  );
  const [secondDimension, setSecondDimension] = useState(data.categories[1]);
  const [theme, setTheme] = useState<"light" | "dark">("light");
  const [height, setHeight] = useState(360);
  const rendered = analysisOption(
    result,
    type,
    dimension,
    metrics,
    secondDimension,
  );
  return (
    <section className="top-space">
      <h3>结果图表</h3>
      <Space wrap className="chart-controls">
        <Select
          aria-label="图表类型"
          value={type}
          onChange={setType}
          options={chartTypes}
        />
        <Select
          aria-label="分类维度"
          value={dimension}
          onChange={setDimension}
          options={data.columns.map((key) => ({ value: key, label: key }))}
        />
        {type === "heatmap" && (
          <Select
            aria-label="第二分类维度"
            value={secondDimension}
            onChange={setSecondDimension}
            placeholder="第二分类维度"
            options={data.columns
              .filter((key) => key !== dimension)
              .map((key) => ({ value: key, label: key }))}
          />
        )}
        <Select
          aria-label="数值指标"
          mode="multiple"
          value={metrics}
          onChange={setMetrics}
          placeholder="选择数值指标"
          style={{ minWidth: 160 }}
          options={data.numeric.map((key) => ({ value: key, label: key }))}
        />
        <Select
          aria-label="图表主题"
          value={theme}
          onChange={setTheme}
          options={[
            { value: "light", label: "浅色主题" },
            { value: "dark", label: "深色主题" },
          ]}
        />
        <Select
          aria-label="图表尺寸"
          value={height}
          onChange={setHeight}
          options={[
            { value: 280, label: "紧凑" },
            { value: 360, label: "标准" },
            { value: 520, label: "宽展" },
          ]}
        />
      </Space>
      <p className="muted">
        分类图展示前50行；雷达图展示前10行且需三个指标；饼图与热力图使用第一个指标，热力图最多500行。完整结果可在上方表格核对。
      </p>
      {rendered.reason ? (
        <Alert type="info" message={rendered.reason} />
      ) : (
        <Chart
          option={rendered.option!}
          label={`授权数据查询${chartTypes.find((item) => item.value === type)?.label}`}
          theme={theme}
          height={height}
        />
      )}
    </section>
  );
}
export function MatchDimensions({ dimensions }: { dimensions?: Row }) {
  if (!dimensions) return null;
  const names: Record<string, string> = {
    skills: "专业技能",
    experience: "工作经验",
    projects: "项目相关性",
    bonus: "岗位加分项",
    education: "学历条件（旧版）",
    other: "其他条件（旧版）",
  };
  return (
    <Descriptions
      size="small"
      column={1}
      bordered
      items={Object.entries(dimensions).map(([key, value]) => {
        const score = typeof value === "number" ? value : value?.score;
        const weight =
          typeof value?.weight === "number"
            ? `（权重 ${Math.round(value.weight * 100)}%）`
            : "";
        return {
          key,
          label: `${names[key] || key}${weight}`,
          children: score == null ? "未设置，不参与评分" : `${score} 分`,
        };
      })}
    />
  );
}
export function TaskResult({ run }: { run: Row }) {
  const result = run.result;
  if (!result) return null;
  if (result.needs_clarification)
    return (
      <Alert
        type="info"
        showIcon
        message="需要补充信息"
        description={
          <div>
            <p>{result.question || "请补充分析范围或统计口径。"}</p>
            <p>请在下方回答，继续本次分析。</p>
          </div>
        }
      />
    );
  if (
    Array.isArray(result.items) &&
    (run.kind === "search" || result.items.some((row: Row) => row.talent_id))
  )
    return (
      <>
        <h3>人才检索结果</h3>
        <p className="muted">检索相关度用于排序；请核对档案与原文证据。</p>
        <List
          dataSource={result.items as Row[]}
          locale={{ emptyText: "没有找到相关人才，请调整需求或补充档案。" }}
          renderItem={(row) => (
            <List.Item>
              <div className="full">
                <h4>{row.name || row.talent_id}</h4>
                <Detail
                  value={{
                    revision: row.revision,
                    similarity: row.similarity,
                    evidence: row.evidence,
                  }}
                />
                <details>
                  <summary>人才画像</summary>
                  <Detail value={row.profile} />
                </details>
              </div>
            </List.Item>
          )}
        />
      </>
    );
  if (result.candidates) {
    const candidates: Row[] = result.candidates;
    return (
      <>
        <h3>岗位匹配结果</h3>
        <a href={`/api/v1/matches/${run.id}/export.csv`} download>
          导出候选人 CSV
        </a>
        {!!candidates.length && (
          <Chart
            label="候选人匹配总分（具体评分与证据见下方）"
            option={{
              tooltip: { trigger: "axis" },
              grid: { left: 110, right: 24, bottom: 30, top: 15 },
              xAxis: { type: "value", max: 100 },
              yAxis: {
                type: "category",
                inverse: true,
                data: candidates.slice(0, 10).map((x) => x.name),
              },
              series: [
                {
                  name: "总分",
                  type: "bar",
                  data: candidates
                    .slice(0, 10)
                    .map((x) =>
                      typeof x.score?.total === "number" ? x.score.total : null,
                    ),
                  label: { show: true, position: "right" },
                },
              ],
            }}
          />
        )}
        <List
          dataSource={candidates}
          locale={{
            emptyText: "没有符合条件的候选人，请核对岗位要求或补充人才档案。",
          }}
          renderItem={(candidate) => (
            <List.Item>
              <div className="full">
                <div className="row">
                  <strong>{candidate.name}</strong>
                  <Tag>
                    {typeof candidate.score?.total === "number"
                      ? `${candidate.score.total} 分`
                      : "总分未设置"}
                  </Tag>
                  <Tag>
                    {candidate.score?.eligible === true
                      ? "满足必要条件"
                      : candidate.score?.eligible === false
                        ? "不满足必要条件"
                        : "必要条件待核实"}
                  </Tag>
                  <span className="muted">档案版本 {candidate.revision}</span>
                </div>
                <Detail
                  value={Object.fromEntries(
                    Object.entries(candidate.score || {}).filter(
                      ([key]) => key !== "dimensions",
                    ),
                  )}
                />
                <MatchDimensions dimensions={candidate.score?.dimensions} />
                <details>
                  <summary>人才画像与原文证据</summary>
                  <Detail value={candidate.profile} />
                </details>
              </div>
            </List.Item>
          )}
        />
        <details>
          <summary>诊断及版本</summary>
          <Detail
            value={{
              diagnostics: result.diagnostics,
              versions: result.versions,
            }}
          />
        </details>
      </>
    );
  }
  if (result.answer)
    return (
      <>
        <div className="answer preserve">{result.answer}</div>
        {result.sql && (
          <details open>
            <summary>查询 SQL</summary>
            <pre>{result.sql}</pre>
          </details>
        )}
        {result.columns && (
          <Table
            size="small"
            rowKey={(_, i) => String(i)}
            scroll={{ x: true }}
            dataSource={(result.rows || []).map((row: any) =>
              Array.isArray(row)
                ? Object.fromEntries(
                    result.columns.map((key: string, i: number) => [
                      key,
                      row[i],
                    ]),
                  )
                : row,
            )}
            columns={result.columns.map((key: string) => ({
              title: key,
              dataIndex: key,
              render: (v: any) => <Detail value={v} />,
            }))}
          />
        )}
        {!!result.columns?.length && result.rows ? (
          <AnalysisChart key={run.id} result={result} />
        ) : (
          chartOption(result.chart) && (
            <Chart
              label="授权数据查询图表"
              option={chartOption(result.chart)!}
            />
          )
        )}
        {result.report_id && (
          <Space>
            <a href={`/api/v1/reports/${result.report_id}/export?format=docx`}>
              下载 Word 报告
            </a>
            <a href={`/api/v1/reports/${result.report_id}/export?format=pdf`}>
              下载 PDF 报告
            </a>
          </Space>
        )}
        {result.citations && (
          <>
            <h3>回答依据</h3>
            <List
              dataSource={result.citations as Row[]}
              locale={{ emptyText: "本次回答未返回可核对的引用。" }}
              renderItem={(citation) => (
                <List.Item>
                  <blockquote>
                    <strong>{citation.title || citation.source_id}</strong>
                    <p>{citation.quote}</p>
                    <span className="muted">
                      来源编号：{citation.source_id}
                    </span>
                  </blockquote>
                </List.Item>
              )}
            />
          </>
        )}
      </>
    );
  return <Detail value={result} />;
}
export function TaskPanel({
  id,
  onComplete,
}: {
  id: string;
  onComplete?: (run?: Row) => void;
}) {
  const { data: run, error, loading, reload } = useResource(`runs/${id}`);
  const [actionError, setActionError] = useState<unknown>();
  const completed = useRef(false);
  const latest = useRef(onComplete);
  latest.current = onComplete;
  useEffect(() => {
    completed.current = false;
  }, [id]);
  const terminal =
    run &&
    ["completed", "succeeded", "failed", "cancelled"].includes(run.status);
  useEffect(() => {
    if (terminal) {
      if (!completed.current) {
        completed.current = true;
        latest.current?.(run);
      }
      return;
    }
    const timer = window.setInterval(() => void reload(), 3000);
    let source: EventSource | undefined;
    if (typeof EventSource !== "undefined") {
      source = new EventSource(`/api/v1/runs/${id}/events`, {
        withCredentials: true,
      });
      source.onmessage = () => void reload();
      for (const name of ["progress", "status", "completed", "failed", "run"])
        source.addEventListener(name, () => void reload());
    }
    return () => {
      clearInterval(timer);
      source?.close();
    };
  }, [id, reload, terminal]);
  if (error) return <Failure error={error} retry={reload} />;
  if (!run) return <Spin spinning={loading} />;
  return (
    <div className="task-panel">
      <Space wrap>
        <Status value={run.status} />
        <Typography.Text copyable>{run.id}</Typography.Text>
        <Button onClick={reload}>刷新</Button>
        {!terminal && (
          <Popconfirm
            title="取消此任务？"
            onConfirm={async () => {
              try {
                await post(`runs/${id}/cancel`);
                void reload();
              } catch (e) {
                setActionError(e);
              }
            }}
          >
            <Button danger>取消任务</Button>
          </Popconfirm>
        )}
      </Space>
      {!!actionError && <Failure error={actionError} />}
      <Progress
        percent={
          typeof run.progress === "number"
            ? run.progress <= 1
              ? Math.round(run.progress * 100)
              : run.progress
            : terminal
              ? 100
              : 0
        }
        status={
          run.status === "failed" ? "exception" : terminal ? "normal" : "active"
        }
      />
      {run.error && (
        <Alert
          type="error"
          message="任务失败"
          description={
            typeof run.error === "string" ? run.error : json(run.error)
          }
        />
      )}
      <TaskResult run={run} />
      {run.versions && (
        <details>
          <summary>运行版本</summary>
          <Detail value={run.versions} />
        </details>
      )}
    </div>
  );
}

const references: Record<string, string> = {
  org_id: "organizations",
  talent_id: "talents",
  question_ids: "questions",
  course_ids: "courses",
  skill_id: "skills",
  role_template_id: "roles",
};
export function Editor({
  resource,
  record,
  onClose,
  onSaved,
}: {
  resource: string;
  record?: Row;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [form] = Form.useForm();
  const [error, setError] = useState<unknown>();
  const [saving, setSaving] = useState(false);
  const [lookups, setLookups] = useState<Record<string, Row[]>>({});
  const schema = schemas[resource];
  const trigger =
    Form.useWatch("trigger", form) || record?.trigger || "schedule";
  const roleTemplate = Form.useWatch("role_template_id", form);
  const shown = (field: Field) =>
    !field.when ||
    (field.when.field === "trigger"
      ? trigger
      : form.getFieldValue(field.when.field)) === field.when.value;
  useEffect(() => {
    const names = [
      ...new Set(schema.fields.map((x) => references[x.name]).filter(Boolean)),
    ];
    let active = true;
    void Promise.allSettled(
      names.map(async (name) => [name, items(await api(name))] as const),
    ).then((results) => {
      if (active)
        setLookups(
          Object.fromEntries(
            results.flatMap((result) =>
              result.status === "fulfilled" ? [result.value] : [],
            ),
          ),
        );
    });
    return () => {
      active = false;
    };
  }, [schema]);
  const initial = Object.fromEntries(
    schema.fields.map((field) => {
      const value = record?.[field.name];
      return [
        field.name,
        field.type === "json" && value != null
          ? json(value)
          : field.type === "list" &&
              !references[field.name] &&
              !["permissions", "denied_fields"].includes(field.name)
            ? (value || []).join("\n")
            : (value ??
              field.defaultValue ??
              (field.type === "boolean" ? true : undefined)),
      ];
    }),
  );
  const input = (field: Field): ReactNode => {
    if (field.name === "permissions")
      return (
        <Select
          mode="tags"
          aria-label="允许操作"
          options={Object.entries({
            dashboard: "工作概览",
            talents: "人才档案",
            jobs: "岗位",
            questions: "题库",
            assessments: "测评",
            courses: "课程",
            "training-plans": "培训计划",
            knowledge: "知识",
            chat: "知识助手",
            analysis: "数据问数",
            approvals: "审批",
            notifications: "通知",
            runs: "任务",
            issues: "异常",
            audits: "操作审计",
            users: "账号",
            organizations: "组织",
            roles: "角色模板",
            skills: "Skills",
            automations: "自动化",
            system: "系统状态",
          }).flatMap(([key, title]) => [
            { label: `查看${title}`, value: `GET:${key}` },
            { label: `新增/执行${title}`, value: `POST:${key}` },
            { label: `修改${title}`, value: `PATCH:${key}` },
            { label: `删除${title}`, value: `DELETE:${key}` },
          ])}
        />
      );
    if (field.name === "denied_fields")
      return (
        <Select
          mode="tags"
          options={[
            { label: "电话", value: "phone" },
            { label: "邮箱", value: "email" },
            { label: "证件号码", value: "id_number" },
            { label: "薪酬", value: "salary" },
            { label: "原文正文", value: "text" },
          ]}
        />
      );
    const reference = references[field.name];
    if (reference)
      return (
        <Select
          showSearch
          optionFilterProp="label"
          allowClear
          onChange={(value) => {
            if (field.name === "role_template_id" && value)
              form.setFieldValue(
                "role",
                lookups.roles?.find((item) => item.id === value)?.base_role,
              );
          }}
          mode={field.type === "list" ? "multiple" : undefined}
          options={(lookups[reference] || []).map((row) => ({
            label: `${label(row)} (${row.id})`,
            value: row.id,
          }))}
        />
      );
    if (field.type === "boolean") return <Checkbox>启用</Checkbox>;
    if (field.type === "select")
      return (
        <Select
          disabled={
            resource === "users" && field.name === "role" && !!roleTemplate
          }
          options={field.options?.map((value) => ({
            label:
              (
                {
                  admin: "系统管理员",
                  hr: "人力资源",
                  manager: "部门主管",
                  employee: "员工",
                  single: "单选题",
                  multiple: "多选题",
                  text: "主观题",
                  org: "所属组织",
                  self: "仅本人",
                  schedule: "定时触发",
                  event: "事件触发",
                  resume: "履历处理完成",
                  assessment: "测评处理完成",
                  training: "培养计划生成",
                  job: "岗位解析完成",
                } as Record<string, string>
              )[value] || value,
            value,
          }))}
        />
      );
    if (field.type === "number")
      return <InputNumber min={field.min ?? 0} className="full" />;
    if (field.type === "password")
      return <Input.Password autoComplete="new-password" />;
    if (["textarea", "list", "json"].includes(field.type || ""))
      return <Input.TextArea autoSize={{ minRows: 3, maxRows: 12 }} />;
    return <Input />;
  };
  return (
    <Modal
      open
      title={`${record ? "编辑" : "新建"}${schema.title}`}
      onCancel={onClose}
      onOk={() => form.submit()}
      confirmLoading={saving}
      okText="保存"
      cancelText="取消"
      width={680}
      destroyOnClose
    >
      <Form
        form={form}
        layout="vertical"
        initialValues={initial}
        onFinish={async (values) => {
          setSaving(true);
          setError(undefined);
          try {
            const payload: Row = {};
            for (const field of schema.fields) {
              if (!shown(field)) continue;
              const v = values[field.name];
              if (field.type === "password" && !v) continue;
              if (field.type === "json") {
                if (v?.trim()) payload[field.name] = JSON.parse(v);
              } else if (field.type === "list")
                payload[field.name] = Array.isArray(v)
                  ? v
                  : String(v || "")
                      .split("\n")
                      .map((x) => x.trim())
                      .filter(Boolean);
              else if (v !== undefined && v !== "") payload[field.name] = v;
            }
            if (resource === "users" && !record && !payload.password)
              throw new Error("新建账号必须填写密码");
            if (resource === "users" && payload.role_template_id)
              delete payload.role;
            if (
              resource === "users" &&
              record?.role_template_id &&
              !values.role_template_id
            )
              payload.role_template_id = null;
            if (
              resource === "automations" &&
              payload.trigger === "schedule" &&
              payload.interval_seconds < 60
            )
              throw new Error("定时间隔至少60秒");
            await (record
              ? patch(`${resource}/${record.id}`, payload)
              : post(resource, payload));
            onSaved();
            onClose();
          } catch (e) {
            setError(e);
          } finally {
            setSaving(false);
          }
        }}
      >
        {!!error && <Failure error={error} />}
        {schema.fields.filter(shown).map((field) => (
          <Form.Item
            key={field.name}
            name={field.name}
            label={field.label}
            extra={field.help}
            valuePropName={field.type === "boolean" ? "checked" : "value"}
            rules={
              field.required &&
              !(resource === "users" && field.name === "role" && roleTemplate)
                ? [{ required: true, message: `请填写${field.label}` }]
                : []
            }
          >
            {input(field)}
          </Form.Item>
        ))}
      </Form>
    </Modal>
  );
}

export function ResourceTable({
  resource,
  toolbar,
  actions,
  onSelect,
  editable = true,
  refresh = 0,
}: {
  resource: string;
  toolbar?: ReactNode;
  actions?: (row: Row, reload: () => void) => ReactNode;
  onSelect?: (row: Row) => void;
  editable?: boolean;
  refresh?: number;
}) {
  const { data, error, loading, reload } = useResource(resource);
  const [query, setQuery] = useState("");
  const [edit, setEdit] = useState<Row | true>();
  const [detail, setDetail] = useState<Row>();
  const [mutationError, setMutationError] = useState<unknown>();
  const schema = schemas[resource] || { title: resource, readonly: true };
  useEffect(() => {
    if (refresh) void reload();
  }, [refresh, reload]);
  const rows = items(data).filter((row) =>
    json(row).toLowerCase().includes(query.toLowerCase()),
  );
  const columns = [
    {
      title: schema.title || "名称",
      key: "title",
      render: (_: any, row: Row) => (
        <Button
          type="link"
          className="name-button"
          onClick={() => (onSelect ? onSelect(row) : setDetail(row))}
        >
          {label(row)}
        </Button>
      ),
    },
    {
      title: "状态 / 角色",
      key: "status",
      render: (_: any, row: Row) =>
        row.status ? (
          <Status value={row.status} />
        ) : row.role ? (
          <Tag>
            {
              (
                {
                  admin: "管理员",
                  hr: "人力资源",
                  manager: "主管",
                  employee: "员工",
                } as Row
              )[row.role]
            }
          </Tag>
        ) : typeof row.enabled === "boolean" ? (
          <Tag>{row.enabled ? "启用" : "停用"}</Tag>
        ) : row.read === false ? (
          <Tag color="processing">未读</Tag>
        ) : (
          <span className="muted">—</span>
        ),
    },
    {
      title: "更新时间",
      key: "updated",
      render: (_: any, row: Row) =>
        row.updated_at || row.created_at
          ? new Date(row.updated_at || row.created_at).toLocaleString("zh-CN")
          : "—",
    },
    {
      title: "操作",
      key: "actions",
      render: (_: any, row: Row) => (
        <Space wrap>
          {actions?.(row, reload)}
          {editable && !schema.readonly && (
            <Button size="small" onClick={() => setEdit(row)}>
              编辑
            </Button>
          )}
          {editable &&
            ["talents", "jobs", "knowledge", "courses", "questions"].includes(
              resource,
            ) && (
              <Popconfirm
                title="删除这条记录？"
                description="删除后该记录将从可用列表中移除。"
                onConfirm={async () => {
                  setMutationError(undefined);
                  try {
                    await api(`${resource}/${row.id}`, { method: "DELETE" });
                    void reload();
                  } catch (e) {
                    setMutationError(e);
                  }
                }}
              >
                <Button size="small" danger>
                  删除
                </Button>
              </Popconfirm>
            )}
        </Space>
      ),
    },
  ];
  return (
    <>
      <div className="toolbar">
        <Input.Search
          aria-label={`搜索${schema.title}`}
          placeholder={`搜索${schema.title}、技能或编号`}
          allowClear
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          className="search"
        />
        <Space wrap>
          {toolbar}
          <Button onClick={reload}>刷新</Button>
          {editable && !schema.readonly && (
            <Button type="primary" onClick={() => setEdit(true)}>
              新建{schema.title}
            </Button>
          )}
        </Space>
      </div>
      {!!mutationError && <Failure error={mutationError} />}
      {error ? (
        <Failure error={error} retry={reload} />
      ) : (
        <Table
          rowKey="id"
          loading={loading}
          dataSource={rows}
          columns={columns}
          scroll={{ x: 700 }}
          pagination={{
            pageSize: 10,
            showSizeChanger: true,
            showTotal: (total) => `共 ${total} 条`,
          }}
          locale={{
            emptyText: (
              <Empty
                description={`暂无${schema.title}，可通过上方入口添加或等待分配。`}
              />
            ),
          }}
        />
      )}
      {edit && (
        <Editor
          resource={resource}
          record={edit === true ? undefined : edit}
          onClose={() => setEdit(undefined)}
          onSaved={reload}
        />
      )}
      <Drawer
        open={!!detail}
        onClose={() => setDetail(undefined)}
        title={detail ? label(detail) : "详情"}
        width={760}
      >
        <Detail value={detail} />
      </Drawer>
    </>
  );
}

export function AssessmentPlayer({
  record,
  onClose,
  onRun,
}: {
  record: Row;
  onClose: () => void;
  onRun: (id: string) => void;
}) {
  const [exam, setExam] = useState<Row>();
  const [answers, setAnswers] = useState<Row>({});
  const [error, setError] = useState<unknown>();
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<Row>();
  const events = useRef<Row[]>([]);
  const [remaining, setRemaining] = useState<number>();
  const { message } = AntApp.useApp();
  useEffect(() => {
    let active = true;
    void api(`assessments/${record.id}`)
      .then((data) => {
        if (active) {
          setExam(data);
          if (["in_progress", "started"].includes(data.status))
            setRemaining(deadlineRemaining(data));
        }
      })
      .catch(setError);
    return () => {
      active = false;
    };
  }, [record.id]);
  useEffect(() => {
    if (remaining === undefined) return;
    const timer = setInterval(
      () => setRemaining((value) => Math.max(0, (value || 0) - 1)),
      1000,
    );
    const hidden = () => {
      if (document.hidden)
        events.current.push({
          type: "visibility",
          at: new Date().toISOString(),
        });
    };
    document.addEventListener("visibilitychange", hidden);
    return () => {
      clearInterval(timer);
      document.removeEventListener("visibilitychange", hidden);
    };
  }, [remaining === undefined]);
  return (
    <Drawer open title={record.title} onClose={onClose} width={760}>
      {!!error && <Failure error={error} />}
      {!exam ? (
        <Spin />
      ) : (
        <>
          <Space wrap>
            <Status value={exam.status} />
            <span>时长 {exam.duration_minutes} 分钟</span>
            {remaining !== undefined && (
              <Tag color={remaining < 60 ? "warning" : "default"}>
                剩余 {Math.floor(remaining / 60)}:
                {String(remaining % 60).padStart(2, "0")}
              </Tag>
            )}
          </Space>
          {["published", "approved"].includes(exam.status) && (
            <Button
              type="primary"
              loading={busy}
              onClick={async () => {
                setBusy(true);
                try {
                  const started = await post(`assessments/${exam.id}/start`);
                  setExam({ ...exam, ...started });
                  setRemaining(deadlineRemaining({ ...exam, ...started }));
                  events.current.push({
                    type: "start",
                    at: new Date().toISOString(),
                  });
                } catch (e) {
                  setError(e);
                } finally {
                  setBusy(false);
                }
              }}
            >
              开始测评
            </Button>
          )}
          {["in_progress", "running", "started"].includes(exam.status) && (
            <div className="exam-questions">
              {(exam.questions || []).map((question: Row, index: number) => (
                <section key={question.id}>
                  <h3>
                    {index + 1}. {question.title}{" "}
                    <small>{question.points} 分</small>
                  </h3>
                  {question.question_type === "single" ? (
                    <Radio.Group
                      value={answers[question.id]}
                      onChange={(event) =>
                        setAnswers({
                          ...answers,
                          [question.id]: event.target.value,
                        })
                      }
                      options={(question.options || []).map(
                        (value: string) => ({ label: value, value }),
                      )}
                    />
                  ) : question.question_type === "multiple" ? (
                    <Checkbox.Group
                      value={answers[question.id]}
                      onChange={(value) =>
                        setAnswers({ ...answers, [question.id]: value })
                      }
                      options={(question.options || []).map(
                        (value: string) => ({ label: value, value }),
                      )}
                    />
                  ) : (
                    <Input.TextArea
                      rows={5}
                      aria-label={question.title}
                      value={answers[question.id]}
                      onChange={(event) =>
                        setAnswers({
                          ...answers,
                          [question.id]: event.target.value,
                        })
                      }
                    />
                  )}
                </section>
              ))}
              {!(exam.questions || []).length ? (
                <Alert
                  type="warning"
                  message="题目尚未加载，请关闭并重新打开；若仍无题目，请联系管理员。"
                />
              ) : (
                <Popconfirm
                  title="提交后将进入评分，是否提交？"
                  onConfirm={async () => {
                    setBusy(true);
                    setError(undefined);
                    try {
                      const submitted = await post(
                        `assessments/${exam.id}/submit`,
                        { answers, events: events.current },
                      );
                      setExam({ ...exam, status: "submitted" });
                      onRun(submitted.id);
                      message.success("答卷已提交，正在评分");
                    } catch (e) {
                      setError(e);
                    } finally {
                      setBusy(false);
                    }
                  }}
                >
                  <Button type="primary" loading={busy}>
                    提交答卷（已答 {Object.keys(answers).length}/
                    {exam.questions.length}）
                  </Button>
                </Popconfirm>
              )}
            </div>
          )}
          <Button
            className="top-space"
            onClick={async () => {
              try {
                setResult(await api(`assessments/${exam.id}/result`));
              } catch (e) {
                setError(e);
              }
            }}
          >
            查看测评结果
          </Button>
          {result && (
            <>
              <h3>能力评估</h3>
              <Alert
                type="info"
                message="模型推断结果，请结合业务证据人工复核。"
              />
              {result.id ? (
                <TaskPanel id={result.id} />
              ) : (
                <Detail value={result} />
              )}
            </>
          )}
        </>
      )}
    </Drawer>
  );
}
