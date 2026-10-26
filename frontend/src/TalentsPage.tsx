import { useState } from "react";
import {
  App,
  Button,
  Collapse,
  Descriptions,
  Drawer,
  Form,
  Input,
  InputNumber,
  Modal,
  Popconfirm,
  Select,
  Space,
  Table,
  Tabs,
  Tag,
  Timeline,
  Typography,
} from "antd";
import {
  DeleteOutlined,
  PlusOutlined,
  ReloadOutlined,
} from "@ant-design/icons";
import { api, useResource } from "./api";
import type { Profile, Talent } from "./types";
import {
  date,
  display,
  EmptyPanel,
  ErrorPanel,
  EvidenceList,
  TagsField,
} from "./ui";
export default function TalentsPage() {
  const [query, setQuery] = useState("");
  const [page, setPage] = useState(1);
  const [id, setId] = useState<string | null>(null);
  const talents = useResource<{ items: Talent[]; total: number }>(
    `/talents?q=${encodeURIComponent(query)}&page=${page}&page_size=20`,
  );
  return (
    <>
      <div className="page-heading">
        <div>
          <h1>人才库</h1>
          <p>查看结构化档案，核对原文，维护可用于匹配的最新信息。</p>
        </div>
        <Button icon={<ReloadOutlined />} onClick={talents.reload}>
          刷新
        </Button>
      </div>
      <section className="panel">
        <div className="table-toolbar">
          <Input.Search
            allowClear
            placeholder="搜索姓名、手机号或邮箱"
            aria-label="搜索人才"
            onSearch={(value) => {
              setQuery(value);
              setPage(1);
            }}
            style={{ maxWidth: 440 }}
          />
          <span className="muted">共 {talents.data?.total ?? "—"} 份档案</span>
        </div>
        <ErrorPanel error={talents.error} reload={talents.reload} />
        <Table
          rowKey="id"
          loading={talents.loading}
          dataSource={talents.data?.items}
          scroll={{ x: 800 }}
          locale={{
            emptyText: (
              <EmptyPanel
                text={
                  query
                    ? "没有找到相关人才，请调整搜索条件。"
                    : "人才库为空。前往任务中心导入简历。"
                }
              />
            ),
          }}
          pagination={{
            current: page,
            pageSize: 20,
            total: talents.data?.total,
            onChange: setPage,
            showSizeChanger: false,
            showTotal: (total) => `共 ${total} 份`,
          }}
          columns={[
            {
              title: "姓名",
              render: (_, talent) => (
                <Button
                  className="text-button"
                  type="link"
                  onClick={() => setId(talent.id)}
                >
                  {talent.name || talent.profile.name || "未识别姓名"}
                </Button>
              ),
            },
            {
              title: "联系方式",
              render: (_, talent) => (
                <div>
                  {talent.profile.phone || "未提供电话"}
                  <div className="muted">
                    {talent.profile.email || "未提供邮箱"}
                  </div>
                </div>
              ),
            },
            {
              title: "技能",
              render: (_, talent) => (
                <Space size={[0, 4]} wrap>
                  {talent.profile.skills.slice(0, 4).map((skill) => (
                    <Tag key={skill}>{skill}</Tag>
                  ))}
                  {talent.profile.skills.length > 4 && (
                    <Tag>+{talent.profile.skills.length - 4}</Tag>
                  )}
                </Space>
              ),
            },
            {
              title: "所在地",
              render: (_, talent) => display(talent.profile.location),
            },
            {
              title: "匹配状态",
              render: (_, talent) => (
                <Tag
                  color={
                    talent.indexed_revision === talent.revision
                      ? "success"
                      : "warning"
                  }
                >
                  {talent.indexed_revision === talent.revision
                    ? "可参与匹配"
                    : "等待更新"}
                </Tag>
              ),
            },
            {
              title: "操作",
              render: (_, talent) => (
                <Button onClick={() => setId(talent.id)} size="small">
                  查看档案
                </Button>
              ),
            },
          ]}
        />
      </section>
      <TalentDrawer
        id={id}
        onClose={() => setId(null)}
        onChange={talents.reload}
      />
    </>
  );
}
export function TalentDrawer({
  id,
  onClose,
  onChange,
}: {
  id: string | null;
  onClose: () => void;
  onChange?: () => void;
}) {
  const talent = useResource<Talent>(id ? `/talents/${id}` : null);
  const [editing, setEditing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [editError, setEditError] = useState("");
  const [form] = Form.useForm<Profile>();
  const { message } = App.useApp();
  function edit() {
    form.setFieldsValue(structuredClone(talent.data!.profile));
    setEditError("");
    setEditing(true);
  }
  async function save() {
    if (!talent.data) return;
    const values = await form.validateFields();
    setSaving(true);
    setEditError("");
    try {
      await api(`/talents/${id}`, {
        method: "PUT",
        body: JSON.stringify({
          profile: { ...talent.data.profile, ...values },
          revision: talent.data.revision,
        }),
      });
      message.success("档案已保存，正在更新检索信息");
      setEditing(false);
      talent.reload();
      onChange?.();
    } catch (e) {
      setEditError((e as Error).message);
    } finally {
      setSaving(false);
    }
  }
  async function remove() {
    try {
      await api(`/talents/${id}`, { method: "DELETE" });
      message.success("档案已删除");
      onClose();
      onChange?.();
    } catch (e) {
      message.error((e as Error).message);
    }
  }
  async function undo(mergeId: string) {
    try {
      await api(`/merges/${mergeId}/undo`, { method: "POST" });
      message.success("合并已撤销");
      talent.reload();
      onChange?.();
    } catch (e) {
      message.error((e as Error).message);
    }
  }
  const p = talent.data?.profile;
  return (
    <>
      <Drawer
        title={talent.data?.name || p?.name || "人才档案"}
        width={800}
        open={Boolean(id)}
        onClose={() => {
          setEditing(false);
          onClose();
        }}
        loading={talent.loading}
        extra={
          talent.data && (
            <Space>
              <Button onClick={edit}>编辑档案</Button>
              <Popconfirm
                title="删除这份人才档案？"
                description="删除后不再参与搜索和岗位匹配。"
                onConfirm={remove}
              >
                <Button danger icon={<DeleteOutlined />}>
                  删除
                </Button>
              </Popconfirm>
            </Space>
          )
        }
      >
        <ErrorPanel error={talent.error} reload={talent.reload} />
        {p && talent.data && (
          <>
            <div className="talent-summary">
              <div className="profile-initial">
                {(p.name || "才").slice(0, 1)}
              </div>
              <div>
                <h2>{p.name || "未识别姓名"}</h2>
                <p>
                  {[p.location, p.phone, p.email].filter(Boolean).join(" / ") ||
                    "尚未提供联系方式"}
                </p>
                <Space wrap>
                  <Tag>档案版本 {talent.data.revision}</Tag>
                  <Tag
                    color={
                      talent.data.revision === talent.data.indexed_revision
                        ? "success"
                        : "warning"
                    }
                  >
                    {talent.data.revision === talent.data.indexed_revision
                      ? "可参与匹配"
                      : "正在更新索引"}
                  </Tag>
                </Space>
              </div>
            </div>
            <Tabs
              items={[
                {
                  key: "profile",
                  label: "档案信息",
                  children: (
                    <>
                      <Descriptions
                        size="small"
                        column={2}
                        items={[
                          {
                            key: "months",
                            label: "工作经验",
                            children: p.experience_months
                              ? `${p.experience_months} 个月`
                              : "未提供",
                          },
                          {
                            key: "intentions",
                            label: "求职意向",
                            children: p.intentions.join("、") || "未提供",
                          },
                          {
                            key: "skills",
                            label: "技能",
                            span: 2,
                            children: (
                              <Space wrap>
                                {p.skills.map((value) => (
                                  <Tag key={value}>{value}</Tag>
                                ))}
                              </Space>
                            ),
                          },
                          {
                            key: "certs",
                            label: "证书",
                            span: 2,
                            children: p.certificates.join("、") || "未提供",
                          },
                          {
                            key: "summary",
                            label: "经历摘要",
                            span: 2,
                            children: p.summary || "未提供",
                          },
                        ]}
                      />
                      <h3>工作经历</h3>
                      {p.experiences.length ? (
                        <Timeline
                          items={p.experiences.map((entry, index) => ({
                            key: index,
                            children: (
                              <>
                                <strong>
                                  {entry.company || "未提供公司"} /{" "}
                                  {entry.title || "未提供职位"}
                                </strong>
                                <p className="muted">
                                  {entry.start || "未知"} 至{" "}
                                  {entry.end || "未知"}
                                </p>
                                <p className="preserve-lines">
                                  {entry.description}
                                </p>
                                <Space wrap>
                                  {entry.skills.map((skill) => (
                                    <Tag key={skill}>{skill}</Tag>
                                  ))}
                                </Space>
                              </>
                            ),
                          }))}
                        />
                      ) : (
                        <p className="muted">未提供工作经历</p>
                      )}
                      <h3>教育经历</h3>
                      {p.education.map((entry, index) => (
                        <p key={index}>
                          {[entry.school, entry.degree, entry.major]
                            .filter(Boolean)
                            .join(" / ") || "信息待补充"}
                        </p>
                      ))}
                      {!p.education.length && (
                        <p className="muted">未提供教育经历</p>
                      )}
                      <h3>项目经历</h3>
                      {p.projects.map((entry, index) => (
                        <div className="record" key={index}>
                          <strong>{entry.name || "未命名项目"}</strong>
                          <p className="preserve-lines">{entry.description}</p>
                          <Space wrap>
                            {entry.skills.map((skill) => (
                              <Tag key={skill}>{skill}</Tag>
                            ))}
                          </Space>
                        </div>
                      ))}
                      {!p.projects.length && (
                        <p className="muted">未提供项目经历</p>
                      )}
                      <h3>标签</h3>
                      <Space wrap>
                        {p.tags.map((tag) => (
                          <Tag key={tag}>{tag}</Tag>
                        ))}
                      </Space>
                      {Boolean(p.anomalies.length) && (
                        <>
                          <h3>待核对信息</h3>
                          <ul>
                            {p.anomalies.map((item, index) => (
                              <li key={index}>{item}</li>
                            ))}
                          </ul>
                        </>
                      )}
                    </>
                  ),
                },
                {
                  key: "evidence",
                  label: "原文依据与文件",
                  children: (
                    <>
                      <h3>原始文件</h3>
                      {talent.data.documents?.length ? (
                        talent.data.documents.map((document) => (
                          <p key={document.id}>
                            <a
                              href={`/api/v1/documents/${document.id}/file`}
                              target="_blank"
                              rel="noreferrer"
                            >
                              {document.filename}
                            </a>
                          </p>
                        ))
                      ) : (
                        <p className="muted">暂无原始文件</p>
                      )}
                      <h3>字段依据</h3>
                      <EvidenceList evidence={p.evidence} />
                    </>
                  ),
                },
                {
                  key: "history",
                  label: "修改与合并历史",
                  children: (
                    <>
                      <Timeline
                        items={talent.data.revisions?.map((revision) => ({
                          children: (
                            <>
                              <strong>版本 {revision.revision}</strong>
                              <p>{revision.reason || "档案更新"}</p>
                              <Collapse
                                size="small"
                                items={[
                                  {
                                    key: "details",
                                    label: "查看该版信息",
                                    children: (
                                      <div className="preserve-lines">
                                        {revision.profile.summary || "无摘要"}
                                        <p>
                                          姓名：{display(revision.profile.name)}
                                        </p>
                                        <p>
                                          技能：
                                          {revision.profile.skills.join("、") ||
                                            "未提供"}
                                        </p>
                                        <p>
                                          联系方式：
                                          {[
                                            revision.profile.phone,
                                            revision.profile.email,
                                          ]
                                            .filter(Boolean)
                                            .join(" / ") || "未提供"}
                                        </p>
                                      </div>
                                    ),
                                  },
                                ]}
                              />
                            </>
                          ),
                        }))}
                      />
                      <h3>合并记录</h3>
                      {talent.data.merges?.length ? (
                        talent.data.merges.map((merge) => (
                          <div key={merge.id} className="record">
                            <Space>
                              <span>合并后版本 {merge.after_revision}</span>
                              {merge.undone ? (
                                <Tag>已撤销</Tag>
                              ) : (
                                <Popconfirm
                                  title="撤销这次档案合并？"
                                  description="如果合并后已有修改，系统将拒绝撤销并保留当前档案。"
                                  onConfirm={() => undo(merge.id)}
                                >
                                  <Button size="small">撤销合并</Button>
                                </Popconfirm>
                              )}
                            </Space>
                          </div>
                        ))
                      ) : (
                        <p className="muted">暂无合并记录</p>
                      )}
                    </>
                  ),
                },
              ]}
            />
          </>
        )}
      </Drawer>
      <Modal
        title="编辑人才档案"
        open={editing}
        width={760}
        onCancel={() => setEditing(false)}
        onOk={save}
        confirmLoading={saving}
        okText="保存档案"
        cancelText="取消"
        destroyOnClose
      >
        <ErrorPanel error={editError} />
        <p className="muted">
          只录入已核实的信息；空白表示未知。原始依据会随版本保留。
        </p>
        <Form form={form} layout="vertical">
          <div className="form-grid">
            {[
              { name: "name", label: "姓名" },
              { name: "phone", label: "电话" },
              { name: "email", label: "邮箱" },
              { name: "location", label: "所在地" },
            ].map((field) => (
              <Form.Item key={field.name} {...field}>
                <Input />
              </Form.Item>
            ))}
          </div>
          <Form.Item name="summary" label="经历摘要">
            <Input.TextArea rows={3} />
          </Form.Item>
          <Form.Item name="experience_months" label="工作经验（月）">
            <InputNumber min={0} precision={0} />
          </Form.Item>
          {[
            { name: "skills", label: "技能" },
            { name: "certificates", label: "证书" },
            { name: "intentions", label: "求职意向" },
            { name: "tags", label: "标签" },
          ].map((field) => (
            <TagsField key={field.name} {...field} />
          ))}
          <ProfileLists />
        </Form>
      </Modal>
    </>
  );
}
function ProfileLists() {
  return (
    <Collapse
      items={[
        {
          key: "education",
          label: "教育经历",
          children: (
            <Form.List name="education">
              {(fields, { add, remove }) => (
                <>
                  {fields.map((field) => (
                    <div className="form-record" key={field.key}>
                      <div className="form-grid">
                        {[
                          { key: "school", label: "学校" },
                          { key: "degree", label: "学历" },
                          { key: "major", label: "专业" },
                        ].map((item) => (
                          <Form.Item
                            key={item.key}
                            label={item.label}
                            name={[field.name, item.key]}
                          >
                            <Input />
                          </Form.Item>
                        ))}
                      </div>
                      <Button
                        danger
                        size="small"
                        onClick={() => remove(field.name)}
                      >
                        移除这段教育经历
                      </Button>
                    </div>
                  ))}
                  <Button
                    icon={<PlusOutlined />}
                    onClick={() =>
                      add({ school: null, degree: null, major: null })
                    }
                  >
                    添加教育经历
                  </Button>
                </>
              )}
            </Form.List>
          ),
        },
        {
          key: "experiences",
          label: "工作经历",
          children: (
            <Form.List name="experiences">
              {(fields, { add, remove }) => (
                <>
                  {fields.map((field) => (
                    <div className="form-record" key={field.key}>
                      <div className="form-grid">
                        {[
                          { key: "company", label: "公司" },
                          { key: "title", label: "职位" },
                          { key: "start", label: "开始时间" },
                          { key: "end", label: "结束时间" },
                        ].map((item) => (
                          <Form.Item
                            key={item.key}
                            label={item.label}
                            name={[field.name, item.key]}
                          >
                            <Input />
                          </Form.Item>
                        ))}
                      </div>
                      <Form.Item
                        label="工作描述"
                        name={[field.name, "description"]}
                      >
                        <Input.TextArea rows={3} />
                      </Form.Item>
                      <Form.Item label="相关技能" name={[field.name, "skills"]}>
                        <Select mode="tags" open={false} />
                      </Form.Item>
                      <Button
                        danger
                        size="small"
                        onClick={() => remove(field.name)}
                      >
                        移除这段工作经历
                      </Button>
                    </div>
                  ))}
                  <Button
                    icon={<PlusOutlined />}
                    onClick={() =>
                      add({
                        company: null,
                        title: null,
                        start: null,
                        end: null,
                        description: "",
                        skills: [],
                      })
                    }
                  >
                    添加工作经历
                  </Button>
                </>
              )}
            </Form.List>
          ),
        },
        {
          key: "projects",
          label: "项目经历",
          children: (
            <Form.List name="projects">
              {(fields, { add, remove }) => (
                <>
                  {fields.map((field) => (
                    <div className="form-record" key={field.key}>
                      <Form.Item label="项目名称" name={[field.name, "name"]}>
                        <Input />
                      </Form.Item>
                      <Form.Item
                        label="项目描述"
                        name={[field.name, "description"]}
                      >
                        <Input.TextArea rows={3} />
                      </Form.Item>
                      <Form.Item label="相关技能" name={[field.name, "skills"]}>
                        <Select mode="tags" open={false} />
                      </Form.Item>
                      <Button
                        danger
                        size="small"
                        onClick={() => remove(field.name)}
                      >
                        移除这个项目
                      </Button>
                    </div>
                  ))}
                  <Button
                    icon={<PlusOutlined />}
                    onClick={() =>
                      add({ name: "", description: "", skills: [] })
                    }
                  >
                    添加项目经历
                  </Button>
                </>
              )}
            </Form.List>
          ),
        },
      ]}
    />
  );
}
