import { useState } from "react";
import {
  App,
  Button,
  Drawer,
  Popconfirm,
  Segmented,
  Space,
  Table,
  Tag,
} from "antd";
import { api, useResource } from "./api";
import type { Issue } from "./types";
import { display, EmptyPanel, ErrorPanel, statusText } from "./ui";
import { TalentDrawer } from "./TalentsPage";
export default function IssuesPage() {
  const issues = useResource<Issue[]>("/issues");
  const [filter, setFilter] = useState("pending");
  const [talent, setTalent] = useState<string | null>(null);
  const [detail, setDetail] = useState<Issue | null>(null);
  const [busy, setBusy] = useState<string[]>([]);
  const { message } = App.useApp();
  async function resolve(id: string) {
    setBusy((ids) => [...ids, id]);
    try {
      await api(`/issues/${id}/resolve`, { method: "POST" });
      message.success("已标记为处理完成");
      issues.reload();
    } catch (e) {
      message.error((e as Error).message);
    } finally {
      setBusy((ids) => ids.filter((value) => value !== id));
    }
  }
  const rows = issues.data?.filter(
    (issue) =>
      filter === "all" ||
      (filter === "pending" ? !issue.resolved : issue.resolved),
  );
  return (
    <>
      <div className="page-heading">
        <div>
          <h1>异常与重复</h1>
          <p>核对身份冲突、相似档案和缺失信息，保留每次人工判断。</p>
        </div>
        <Button onClick={issues.reload}>刷新</Button>
      </div>
      <section className="guidance">
        <strong>先核对原文，再处理异常</strong>
        <p>
          相似经历不代表同一人。仅身份信息一致的档案会自动合并；合并记录可在人才详情中查看和撤销。
        </p>
      </section>
      <section className="panel">
        <div className="table-toolbar">
          <Segmented
            value={filter}
            onChange={(value) => setFilter(String(value))}
            options={[
              { label: "待处理", value: "pending" },
              { label: "已处理", value: "resolved" },
              { label: "全部", value: "all" },
            ]}
          />
          <span className="muted">{rows?.length ?? "—"} 条记录</span>
        </div>
        <ErrorPanel error={issues.error} reload={issues.reload} />
        <Table
          rowKey="id"
          loading={issues.loading}
          dataSource={rows}
          scroll={{ x: 650 }}
          pagination={{ pageSize: 15 }}
          locale={{
            emptyText: (
              <EmptyPanel
                text={
                  filter === "pending"
                    ? "目前没有待处理异常。"
                    : "暂无相关记录。"
                }
              />
            ),
          }}
          columns={[
            {
              title: "异常类型",
              dataIndex: "kind",
              render: (value) => (
                <Tag color="warning">{statusText[value] || value}</Tag>
              ),
            },
            {
              title: "说明",
              render: (_, issue) => (
                <Button type="link" onClick={() => setDetail(issue)}>
                  查看异常说明
                </Button>
              ),
            },
            {
              title: "关联档案",
              render: (_, issue) => (
                <Space wrap>
                  <Button
                    size="small"
                    onClick={() => setTalent(issue.talent_id)}
                  >
                    查看档案
                  </Button>
                  {issue.other_id && (
                    <Button
                      size="small"
                      onClick={() => setTalent(issue.other_id!)}
                    >
                      查看对方档案
                    </Button>
                  )}
                </Space>
              ),
            },
            {
              title: "状态",
              render: (_, issue) => (
                <Tag color={issue.resolved ? "success" : "warning"}>
                  {issue.resolved ? "已处理" : "待核对"}
                </Tag>
              ),
            },
            {
              title: "操作",
              render: (_, issue) =>
                issue.resolved ? (
                  "—"
                ) : (
                  <Popconfirm
                    title="已核对并处理这条异常？"
                    description="请先查看关联档案，必要时修正信息。"
                    onConfirm={() => resolve(issue.id)}
                  >
                    <Button loading={busy.includes(issue.id)}>
                      标记已处理
                    </Button>
                  </Popconfirm>
                ),
            },
          ]}
        />
      </section>
      <Drawer
        title="异常说明"
        open={Boolean(detail)}
        onClose={() => setDetail(null)}
      >
        <div className="preserve-lines">{display(detail?.detail)}</div>
      </Drawer>
      <TalentDrawer
        id={talent}
        onClose={() => setTalent(null)}
        onChange={issues.reload}
      />
    </>
  );
}
