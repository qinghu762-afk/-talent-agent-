import { useEffect, useRef, useState } from "react";
import {
  App,
  Alert,
  Button,
  Checkbox,
  Collapse,
  Descriptions,
  Drawer,
  Form,
  Input,
  InputNumber,
  Modal,
  Select,
  Space,
  Table,
  Tabs,
  Tag,
  Upload,
} from "antd";
import { DownloadOutlined, PlusOutlined } from "@ant-design/icons";
import * as echarts from "echarts/core";
import { BarChart, RadarChart } from "echarts/charts";
import {
  GridComponent,
  LegendComponent,
  RadarComponent,
  TooltipComponent,
} from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";
import {
  api,
  isActive,
  toggleComparison,
  useResource,
  validateFiles,
} from "./api";
import type { Candidate, Job, MatchRun, Requirements } from "./types";
import {
  date,
  display,
  EmptyPanel,
  ErrorPanel,
  EvidenceList,
  Status,
  TagsField,
} from "./ui";
import { TalentDrawer } from "./TalentsPage";
echarts.use([
  BarChart,
  RadarChart,
  GridComponent,
  LegendComponent,
  RadarComponent,
  TooltipComponent,
  CanvasRenderer,
]);
export default function JobsPage() {
  const jobs = useResource<Job[]>("/jobs", (data) =>
    data.some((job) => isActive(job.status)),
  );
  const [creating, setCreating] = useState(false);
  const [jobId, setJobId] = useState<string | null>(null);
  const [mode, setMode] = useState("text");
  const [file, setFile] = useState<File | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [form] = Form.useForm();
  const { message } = App.useApp();
  async function create() {
    const values = await form.validateFields();
    if (mode === "file" && !file) {
      setError("请选择岗位文件");
      return;
    }
    if (file && mode === "file") {
      const validation = validateFiles([file], 1, 20, false);
      if (validation) {
        setError(validation);
        return;
      }
    }
    setSaving(true);
    setError("");
    try {
      let body: FormData | string;
      if (mode === "file") {
        body = new FormData();
        body.append("title", values.title);
        body.append("file", file!);
      } else body = JSON.stringify(values);
      await api(mode === "file" ? "/jobs/upload" : "/jobs", {
        method: "POST",
        body,
      });
      message.success("岗位已提交解析，请完成条件核对后开始匹配");
      setCreating(false);
      jobs.reload();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSaving(false);
    }
  }
  return (
    <>
      <div className="page-heading">
        <div>
          <h1>岗位与匹配</h1>
          <p>从招聘需求提取条件，逐项核对，再查看有依据的匹配结果。</p>
        </div>
        <Button
          type="primary"
          icon={<PlusOutlined />}
          onClick={() => {
            form.resetFields();
            setFile(null);
            setError("");
            setCreating(true);
          }}
        >
          新增岗位
        </Button>
      </div>
      <section className="guidance">
        <strong>硬性条件不明，暂不通过</strong>
        <p>
          匹配仅使用已完成检索更新的档案。评分保留岗位快照、档案版本与原文依据，便于后续复核。
        </p>
      </section>
      <section className="panel">
        <div className="table-toolbar">
          <h2>岗位列表</h2>
          <Button onClick={jobs.reload}>刷新</Button>
        </div>
        <ErrorPanel error={jobs.error} reload={jobs.reload} />
        <Table
          rowKey="id"
          loading={jobs.loading}
          dataSource={jobs.data}
          scroll={{ x: 650 }}
          pagination={{ pageSize: 12 }}
          locale={{
            emptyText: (
              <EmptyPanel text="还没有岗位。新增一个岗位，开始寻找合适的人才。" />
            ),
          }}
          columns={[
            {
              title: "岗位名称",
              dataIndex: "title",
              render: (value, job) => (
                <Button type="link" onClick={() => setJobId(job.id)}>
                  {value}
                </Button>
              ),
            },
            {
              title: "必备技能",
              render: (_, job) => (
                <Space wrap>
                  {job.requirements?.required_skills
                    ?.slice(0, 5)
                    .map((skill) => <Tag key={skill}>{skill}</Tag>) ||
                    "等待解析"}
                </Space>
              ),
            },
            {
              title: "状态",
              dataIndex: "status",
              render: (value) => <Status value={value} />,
            },
            { title: "版本", dataIndex: "revision" },
            {
              title: "操作",
              render: (_, job) => (
                <Button onClick={() => setJobId(job.id)}>条件与匹配结果</Button>
              ),
            },
          ]}
        />
      </section>
      <Modal
        title="新增岗位"
        width={680}
        open={creating}
        onCancel={() => setCreating(false)}
        onOk={create}
        confirmLoading={saving}
        okText="提取岗位条件"
        cancelText="取消"
      >
        <ErrorPanel error={error} />
        <Form layout="vertical" form={form}>
          <Form.Item
            label="岗位名称"
            name="title"
            rules={[
              { required: true, whitespace: true, message: "请输入岗位名称" },
            ]}
          >
            <Input maxLength={200} />
          </Form.Item>
          <Tabs
            activeKey={mode}
            onChange={(value) => {
              setMode(value);
              setError("");
            }}
            items={[
              {
                key: "text",
                label: "粘贴岗位说明",
                children: (
                  <Form.Item
                    name="description"
                    label="岗位说明"
                    rules={
                      mode === "text"
                        ? [
                            {
                              required: true,
                              whitespace: true,
                              message: "请输入岗位职责与任职要求",
                            },
                          ]
                        : []
                    }
                  >
                    <Input.TextArea
                      rows={10}
                      placeholder="粘贴完整岗位说明，包括职责、必备条件与加分条件。"
                    />
                  </Form.Item>
                ),
              },
              {
                key: "file",
                label: "上传岗位文件",
                children: (
                  <Upload.Dragger
                    accept=".pdf,.doc,.docx,.png,.jpg,.jpeg,.txt"
                    maxCount={1}
                    fileList={
                      file
                        ? [
                            {
                              uid: file.name,
                              name: file.name,
                              originFileObj:
                                file as import("antd").UploadFile["originFileObj"],
                            },
                          ]
                        : []
                    }
                    beforeUpload={(value) => {
                      setFile(value);
                      return false;
                    }}
                    onRemove={() => setFile(null)}
                  >
                    <p>点击或拖入岗位文件</p>
                    <p className="muted">PDF、Word、图片、文本，最大 20 MB</p>
                  </Upload.Dragger>
                ),
              },
            ]}
          />
        </Form>
      </Modal>
      <JobDrawer
        job={jobs.data?.find((job) => job.id === jobId) || null}
        onClose={() => setJobId(null)}
        onChange={jobs.reload}
      />
    </>
  );
}
function JobDrawer({
  job,
  onClose,
  onChange,
}: {
  job: Job | null;
  onClose: () => void;
  onChange: () => void;
}) {
  const runs = useResource<MatchRun[]>(
    job ? `/jobs/${job.id}/matches` : null,
    (data) => data.some((run) => isActive(run.status)),
  );
  const [runId, setRunId] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [editError, setEditError] = useState("");
  const [form] = Form.useForm();
  const { message } = App.useApp();
  useEffect(() => {
    setRunId(null);
    setEditing(false);
    setEditError("");
  }, [job?.id]);
  function edit() {
    form.resetFields();
    form.setFieldsValue({ title: job!.title, ...job!.requirements });
    setEditing(true);
    setEditError("");
  }
  async function save() {
    const values = await form.validateFields();
    setBusy(true);
    try {
      const { title, ...requirements } = values;
      await api(`/jobs/${job!.id}`, {
        method: "PUT",
        body: JSON.stringify({
          title,
          requirements: { ...job!.requirements, ...requirements },
          revision: job!.revision,
        }),
      });
      message.success("岗位条件已保存");
      setEditing(false);
      onChange();
    } catch (e) {
      setEditError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function match() {
    setBusy(true);
    try {
      const value = await api<{ id: string; task_id: string }>(
        `/jobs/${job!.id}/matches`,
        { method: "POST" },
      );
      message.success("已提交匹配任务");
      runs.reload();
      setRunId(value.id);
    } catch (e) {
      message.error((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  const req = job?.requirements;
  return (
    <>
      <Drawer
        width={880}
        title={job?.title || "岗位详情"}
        open={Boolean(job)}
        onClose={onClose}
        extra={
          <Space>
            <Button disabled={!req} onClick={edit}>
              核对并编辑条件
            </Button>
            <Button
              type="primary"
              disabled={
                !req || isActive(job?.status || "") || job?.status === "failed"
              }
              loading={busy}
              onClick={match}
            >
              开始匹配
            </Button>
          </Space>
        }
      >
        {job && (
          <Tabs
            items={[
              {
                key: "requirements",
                label: "岗位条件",
                children: (
                  <>
                    {isActive(job.status) && (
                      <Alert
                        type="info"
                        showIcon
                        message="正在提取岗位条件，完成后请核对。"
                      />
                    )}
                    {job.status === "failed" && (
                      <Alert
                        type="error"
                        showIcon
                        message="岗位解析失败，请前往任务中心查看原因并重试。"
                      />
                    )}
                    <p className="muted">
                      条件版本 {job.revision}。修改条件后，请重新运行匹配。
                    </p>
                    {req ? (
                      <Descriptions
                        bordered
                        column={1}
                        size="small"
                        items={[
                          {
                            key: "required",
                            label: "必备技能",
                            children:
                              req.required_skills.join("、") || "未设置",
                          },
                          {
                            key: "preferred",
                            label: "加分技能",
                            children:
                              req.preferred_skills.join("、") || "未设置",
                          },
                          {
                            key: "experience",
                            label: "最低经验",
                            children:
                              req.min_experience_months === null
                                ? "未设置"
                                : `${req.min_experience_months} 个月`,
                          },
                          {
                            key: "education",
                            label: "最低学历",
                            children: display(req.min_education),
                          },
                          {
                            key: "certificates",
                            label: "必需证书",
                            children:
                              req.required_certificates.join("、") || "未设置",
                          },
                          {
                            key: "location",
                            label: "工作地点",
                            children: display(req.location),
                          },
                          {
                            key: "responsibilities",
                            label: "工作职责",
                            children: req.responsibilities.map(
                              (value, index) => <p key={index}>{value}</p>,
                            ),
                          },
                        ]}
                      />
                    ) : (
                      <EmptyPanel text="岗位条件尚未提取完成。" />
                    )}
                    <Collapse
                      className="section-space"
                      items={[
                        {
                          key: "source",
                          label: "查看原始岗位说明",
                          children: (
                            <p className="preserve-lines">{job.description}</p>
                          ),
                        },
                        {
                          key: "evidence",
                          label: "条件原文依据",
                          children: (
                            <EvidenceList evidence={req?.evidence || {}} />
                          ),
                        },
                      ]}
                    />
                  </>
                ),
              },
              {
                key: "runs",
                label: "匹配历史",
                children: (
                  <>
                    <ErrorPanel error={runs.error} reload={runs.reload} />
                    <Table
                      rowKey="id"
                      loading={runs.loading}
                      dataSource={runs.data}
                      locale={{
                        emptyText: (
                          <EmptyPanel text="尚未运行匹配。核对岗位条件后，点击开始匹配。" />
                        ),
                      }}
                      columns={[
                        {
                          title: "匹配时间",
                          dataIndex: "created_at",
                          render: date,
                        },
                        {
                          title: "状态",
                          dataIndex: "status",
                          render: (value) => <Status value={value} />,
                        },
                        {
                          title: "人数",
                          render: (_, run) => run.results?.length ?? "—",
                        },
                        {
                          title: "操作",
                          render: (_, run) => (
                            <Button
                              size="small"
                              onClick={() => setRunId(run.id)}
                            >
                              查看结果
                            </Button>
                          ),
                        },
                      ]}
                    />
                  </>
                ),
              },
            ]}
          />
        )}
      </Drawer>
      <Modal
        title="核对岗位条件"
        open={editing}
        onCancel={() => setEditing(false)}
        onOk={save}
        confirmLoading={busy}
        width={700}
        okText="保存条件"
        cancelText="取消"
      >
        <ErrorPanel error={editError} />
        <Form form={form} layout="vertical">
          <Form.Item name="title" label="岗位名称" rules={[{ required: true }]}>
            <Input />
          </Form.Item>
          {[
            { name: "required_skills", label: "必备技能" },
            { name: "preferred_skills", label: "加分技能" },
            { name: "required_certificates", label: "必需证书" },
          ].map((field) => (
            <TagsField key={field.name} {...field} />
          ))}
          <div className="form-grid">
            <Form.Item name="min_experience_months" label="最低工作经验（月）">
              <InputNumber
                min={0}
                max={1200}
                precision={0}
                placeholder="未设置"
              />
            </Form.Item>
            <Form.Item name="min_education" label="最低学历">
              <Input allowClear />
            </Form.Item>
            <Form.Item name="location" label="工作地点">
              <Input allowClear />
            </Form.Item>
          </div>
          <TagsField name="responsibilities" label="工作职责" />
        </Form>
      </Modal>
      <MatchDrawer id={runId} onClose={() => setRunId(null)} />
    </>
  );
}
function MatchDrawer({
  id,
  onClose,
}: {
  id: string | null;
  onClose: () => void;
}) {
  const run = useResource<MatchRun>(id ? `/matches/${id}` : null, (data) =>
    isActive(data.status),
  );
  const [selection, setSelection] = useState<string[]>([]);
  const [candidate, setCandidate] = useState<Candidate | null>(null);
  const [talent, setTalent] = useState<string | null>(null);
  useEffect(() => {
    setSelection([]);
    setCandidate(null);
  }, [id]);
  const results = run.data?.results || [];
  const selected = results.filter((item) => selection.includes(item.talent_id));
  const labels = candidateLabels(results);
  return (
    <>
      <Drawer
        title="岗位匹配结果"
        width={1080}
        open={Boolean(id)}
        onClose={onClose}
        extra={
          run.data &&
          run.data.status === "completed" && (
            <Button
              icon={<DownloadOutlined />}
              href={`/api/v1/matches/${id}/export.csv`}
            >
              导出 CSV
            </Button>
          )
        }
      >
        <ErrorPanel error={run.error} reload={run.reload} />
        {run.data && (
          <>
            <div className="run-meta">
              <Space wrap>
                <Status value={run.data.status} />
                <span>{date(run.data.created_at)}</span>
                <span>
                  耗时 {((run.data.duration_ms || 0) / 1000).toFixed(1)} 秒
                </span>
                <Tag>{results.length} 位候选人</Tag>
              </Space>
            </div>
            {isActive(run.data.status) ? (
              <Alert
                type="info"
                showIcon
                message="匹配任务正在进行，结果会自动更新。"
              />
            ) : (
              <>
                <Alert
                  type="info"
                  showIcon
                  message="严格条件未知视为不通过。分数用于辅助复核，请结合原文依据判断。"
                />
                <div className="table-toolbar">
                  <span>选择最多 3 位候选人比较</span>
                  <Button
                    disabled={!selection.length}
                    onClick={() => setSelection([])}
                  >
                    清空选择
                  </Button>
                </div>
                {selected.length > 0 && (
                  <CompareChart candidates={selected} labels={labels} />
                )}
                <Table
                  rowKey="talent_id"
                  dataSource={results}
                  loading={run.loading}
                  scroll={{ x: 700 }}
                  pagination={{ pageSize: 15 }}
                  locale={{
                    emptyText: (
                      <EmptyPanel
                        text={
                          run.data.status === "failed"
                            ? "本次匹配失败，请在任务中心检查原因并重试。"
                            : "没有可展示的候选人。请确认人才档案已完成索引更新。"
                        }
                      />
                    ),
                  }}
                  columns={[
                    {
                      title: "比较",
                      width: 60,
                      render: (_, item) => (
                        <Checkbox
                          aria-label={`比较 ${labels.get(item.talent_id)}`}
                          checked={selection.includes(item.talent_id)}
                          disabled={
                            selection.length >= 3 &&
                            !selection.includes(item.talent_id)
                          }
                          onChange={() =>
                            setSelection((current) =>
                              toggleComparison(current, item.talent_id),
                            )
                          }
                        />
                      ),
                    },
                    {
                      title: "候选人",
                      render: (_, item) => (
                        <div>
                          <strong>{labels.get(item.talent_id)}</strong>
                          <div className="muted">档案版本 {item.revision}</div>
                        </div>
                      ),
                    },
                    {
                      title: "总分",
                      render: (_, item) => (
                        <strong className="score">
                          {item.score.total.toFixed(1)}
                        </strong>
                      ),
                      sorter: (a, b) => a.score.total - b.score.total,
                      defaultSortOrder: "descend",
                    },
                    {
                      title: "硬性条件",
                      render: (_, item) => (
                        <Tag
                          color={item.score.eligible ? "success" : "warning"}
                        >
                          {item.score.eligible ? "全部通过" : "未全部通过"}
                        </Tag>
                      ),
                    },
                    {
                      title: "主要技能",
                      render: (_, item) =>
                        item.profile.skills.slice(0, 4).join("、") || "未提供",
                    },
                    {
                      title: "操作",
                      render: (_, item) => (
                        <Button onClick={() => setCandidate(item)}>
                          评分与依据
                        </Button>
                      ),
                    },
                  ]}
                />
              </>
            )}
            <Collapse
              className="section-space"
              items={[
                {
                  key: "snapshot",
                  label: "本次岗位快照",
                  children: <Snapshot value={run.data.job_snapshot} />,
                },
                {
                  key: "trace",
                  label: "诊断与模型记录",
                  children: (
                    <>
                      <p>对话模型：{display(run.data.model_versions?.chat)}</p>
                      <p>
                        检索模型：{display(run.data.model_versions?.embedding)}
                      </p>
                      <div className="preserve-lines">
                        {display(run.data.diagnostics)}
                      </div>
                    </>
                  ),
                },
              ]}
            />
          </>
        )}
      </Drawer>
      <Drawer
        width={680}
        title={candidate ? labels.get(candidate.talent_id) : "候选人评分"}
        open={Boolean(candidate)}
        onClose={() => setCandidate(null)}
        extra={
          candidate && (
            <Button onClick={() => setTalent(candidate.talent_id)}>
              查看人才档案
            </Button>
          )
        }
      >
        {candidate && (
          <>
            <div className="candidate-score">
              <span>{candidate.score.total.toFixed(1)}</span>
              <div>
                综合得分
                <Tag color={candidate.score.eligible ? "success" : "warning"}>
                  {candidate.score.eligible
                    ? "硬性条件全部通过"
                    : "硬性条件未全部通过"}
                </Tag>
              </div>
            </div>
            <h3>硬性条件</h3>
            {candidate.score.conditions.map((condition, index) => (
              <div className="condition" key={index}>
                <Space>
                  <Tag
                    color={
                      condition.status === "pass"
                        ? "success"
                        : condition.status === "fail"
                          ? "error"
                          : "warning"
                    }
                  >
                    {condition.status === "pass"
                      ? "通过"
                      : condition.status === "fail"
                        ? "不通过"
                        : "未知 · 不通过"}
                  </Tag>
                  <strong>{condition.label}</strong>
                </Space>
                <p>{condition.evidence || "无可用依据"}</p>
              </div>
            ))}
            <h3>维度评分与依据</h3>
            {candidate.score.dimensions.map((dimension) => (
              <div className="record" key={dimension.key}>
                <div className="panel-heading">
                  <strong>{dimension.label}</strong>
                  <span>
                    {dimension.score.toFixed(1)} 分 · 权重{" "}
                    {(dimension.weight * 100).toFixed(0)}%
                  </span>
                </div>
                <ul>
                  {dimension.evidence.map((evidence, index) => (
                    <li key={index}>{evidence}</li>
                  ))}
                </ul>
              </div>
            ))}
            {[
              { label: "优势", items: candidate.score.strengths },
              { label: "差距", items: candidate.score.gaps },
              { label: "待确认", items: candidate.score.unknowns },
            ].map((section) => (
              <section key={section.label}>
                <h3>{section.label}</h3>
                {section.items.length ? (
                  <ul>
                    {section.items.map((value, index) => (
                      <li key={index}>{value}</li>
                    ))}
                  </ul>
                ) : (
                  <p className="muted">未记录</p>
                )}
              </section>
            ))}
          </>
        )}
      </Drawer>
      <TalentDrawer id={talent} onClose={() => setTalent(null)} />
    </>
  );
}
function Snapshot({ value }: { value: Record<string, unknown> }) {
  const requirements = (value.requirements || value) as Partial<Requirements>;
  return (
    <div>
      <p>
        <strong>{String(value.title || "岗位条件")}</strong>
      </p>
      <p>必备技能：{requirements.required_skills?.join("、") || "未设置"}</p>
      <p>加分技能：{requirements.preferred_skills?.join("、") || "未设置"}</p>
      <p>
        最低经验：
        {requirements.min_experience_months === null ||
        requirements.min_experience_months === undefined
          ? "未设置"
          : `${requirements.min_experience_months} 个月`}
      </p>
      <p>学历：{display(requirements.min_education)}</p>
      <p>
        必需证书：{requirements.required_certificates?.join("、") || "未设置"}
      </p>
      <p>地点：{display(requirements.location)}</p>
      <p>职责：{requirements.responsibilities?.join("；") || "未设置"}</p>
    </div>
  );
}
function candidateLabels(candidates: Candidate[]) {
  const name = (item: Candidate) => item.name?.trim() || "未识别姓名";
  return new Map(
    candidates.map((item) => {
      const namesakes = candidates.filter(
        (other) => name(other) === name(item),
      );
      if (namesakes.length === 1) return [item.talent_id, name(item)];
      const shortId = item.talent_id.slice(0, 8);
      const uniquePrefix =
        namesakes.filter((other) => other.talent_id.startsWith(shortId))
          .length === 1;
      return [
        item.talent_id,
        `${name(item)}（${uniquePrefix ? shortId : item.talent_id}）`,
      ];
    }),
  );
}
function CompareChart({
  candidates,
  labels,
}: {
  candidates: Candidate[];
  labels: Map<string, string>;
}) {
  const element = useRef<HTMLDivElement>(null);
  const [mode, setMode] = useState(
    candidates[0]?.score.dimensions.length >= 3 ? "radar" : "bar",
  );
  useEffect(() => {
    if (!element.current) return;
    const chart = echarts.init(element.current);
    const dimensions = candidates[0]?.score.dimensions || [];
    const colors = ["#2457D6", "#237A57", "#925513"];
    chart.setOption({
      animation: false,
      color: colors,
      tooltip: { trigger: "item" },
      legend: {
        bottom: 0,
        data: candidates.map((item) => labels.get(item.talent_id)),
      },
      ...(mode === "radar"
        ? {
            radar: {
              indicator: dimensions.map((item) => ({
                name: item.label,
                max: 100,
              })),
              radius: "62%",
            },
            series: [
              {
                type: "radar",
                data: candidates.map((item) => ({
                  name: labels.get(item.talent_id),
                  value: dimensions.map(
                    (dimension) =>
                      item.score.dimensions.find((d) => d.key === dimension.key)
                        ?.score || 0,
                  ),
                })),
              },
            ],
          }
        : {
            grid: { top: 24, left: 45, right: 20, bottom: 80 },
            xAxis: {
              type: "category",
              data: dimensions.map((item) => item.label),
            },
            yAxis: { type: "value", min: 0, max: 100 },
            series: candidates.map((item) => ({
              type: "bar",
              name: labels.get(item.talent_id),
              data: dimensions.map(
                (dimension) =>
                  item.score.dimensions.find((d) => d.key === dimension.key)
                    ?.score || 0,
              ),
              barMaxWidth: 34,
            })),
          }),
    });
    const resize = () => chart.resize();
    const observer = new ResizeObserver(resize);
    observer.observe(element.current);
    window.addEventListener("resize", resize);
    return () => {
      observer.disconnect();
      window.removeEventListener("resize", resize);
      chart.dispose();
    };
  }, [candidates, labels, mode]);
  return (
    <section className="comparison">
      <div className="panel-heading">
        <h3>候选人维度比较</h3>
        <Select
          aria-label="图表类型"
          value={mode}
          onChange={setMode}
          options={[
            {
              value: "radar",
              label: "雷达图",
              disabled: (candidates[0]?.score.dimensions.length || 0) < 3,
            },
            { value: "bar", label: "柱状图" },
          ]}
        />
      </div>
      <div
        ref={element}
        className="comparison-chart"
        role="img"
        aria-label="候选人评分维度比较图"
      />
      <details>
        <summary>查看比较数值</summary>
        <table className="accessible-chart">
          <thead>
            <tr>
              <th>维度</th>
              {candidates.map((item) => (
                <th key={item.talent_id}>{labels.get(item.talent_id)}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {candidates[0]?.score.dimensions.map((d) => (
              <tr key={d.key}>
                <th>{d.label}</th>
                {candidates.map((item) => (
                  <td key={item.talent_id}>
                    {item.score.dimensions
                      .find((dimension) => dimension.key === d.key)
                      ?.score.toFixed(1) || "—"}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </details>
    </section>
  );
}
