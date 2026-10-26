import { useEffect, useState } from "react";
import {
  App,
  Button,
  Card,
  Collapse,
  Descriptions,
  Space,
  Statistic,
  Table,
  Tag,
  Upload,
} from "antd";
import { InboxOutlined, ReloadOutlined } from "@ant-design/icons";
import type { UploadFile } from "antd";
import { api, isActive, useResource, validateFiles } from "./api";
import type { Batch, Dashboard, Task } from "./types";
import { date, EmptyPanel, ErrorPanel, Status, statusText } from "./ui";
export default function TasksPage({
  limits,
}: {
  limits?: { batch_files: number; file_mb: number };
}) {
  const batches = useResource<Batch[]>("/batches", (data) =>
    data.some((batch) => batch.items.some((item) => isActive(item.status))),
  );
  const tasks = useResource<Task[]>("/tasks", (data) =>
    data.some((task) => isActive(task.status)),
  );
  const summary = useResource<Dashboard>("/dashboard");
  useEffect(() => {
    if (tasks.data) summary.reload();
  }, [tasks.data, summary.reload]);
  const [files, setFiles] = useState<UploadFile[]>([]);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState("");
  const { message } = App.useApp();
  const [retrying, setRetrying] = useState<string[]>([]);
  const maxFiles = limits?.batch_files || 200;
  const maxMB = limits?.file_mb || 20;
  const refresh = () => {
    batches.reload();
    tasks.reload();
    summary.reload();
  };
  async function upload() {
    const selected = files.map((file) => (file.originFileObj || file) as File);
    const validation = validateFiles(selected, maxFiles, maxMB);
    if (validation) {
      setError(validation);
      return;
    }
    setUploading(true);
    setError("");
    try {
      const form = new FormData();
      selected.forEach((file) => form.append("files", file));
      await api("/batches", { method: "POST", body: form });
      setFiles([]);
      message.success("文件已进入解析队列");
      refresh();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setUploading(false);
    }
  }
  async function retry(id: string) {
    setRetrying((v) => [...v, id]);
    try {
      await api(`/tasks/${id}/retry`, { method: "POST" });
      message.success("已重新加入队列");
      refresh();
    } catch (e) {
      message.error((e as Error).message);
    } finally {
      setRetrying((v) => v.filter((item) => item !== id));
    }
  }
  return (
    <>
      <div className="page-heading">
        <div>
          <h1>任务中心</h1>
          <p>批量导入简历，跟进每个文件的处理进度。</p>
        </div>
        <Button icon={<ReloadOutlined />} onClick={refresh}>
          刷新
        </Button>
      </div>
      <ErrorPanel error={summary.error} reload={summary.reload} />
      <div className="stats-strip">
        {[
          { label: "人才档案", key: "talents" },
          { label: "可匹配档案", key: "indexed" },
          { label: "等待 / 处理中", key: "queued" },
          { label: "待处理异常", key: "issues" },
        ].map((item) => (
          <Statistic
            key={item.key}
            title={item.label}
            value={summary.data?.[item.key as keyof Dashboard] ?? "—"}
          />
        ))}
      </div>
      <section className="panel upload-panel">
        <div className="panel-heading">
          <h2>导入简历</h2>
          <span className="muted">
            每批最多 {maxFiles} 份 · 单文件 {maxMB} MB
          </span>
        </div>
        <Upload.Dragger
          disabled={uploading}
          multiple
          accept=".pdf,.doc,.docx,.png,.jpg,.jpeg,.txt,.zip"
          fileList={files}
          beforeUpload={() => false}
          onChange={({ fileList }) => {
            setFiles(fileList);
            setError("");
          }}
        >
          <p className="ant-upload-drag-icon">
            <InboxOutlined />
          </p>
          <p className="upload-title">将简历拖到这里，或点击选择文件</p>
          <p className="ant-upload-hint">
            PDF、Word、图片、文本或 ZIP 压缩包，逐份解析并保留原始文件
          </p>
        </Upload.Dragger>
        <ErrorPanel error={error} />
        <div className="upload-actions">
          <span className="muted">
            {files.length
              ? `已选择 ${files.length} 份文件`
              : "文件提交后，可在下方查看进度"}
          </span>
          <Button
            type="primary"
            disabled={!files.length}
            loading={uploading}
            onClick={upload}
          >
            开始解析{files.length ? `（${files.length}）` : ""}
          </Button>
        </div>
      </section>
      <section className="panel">
        <div className="panel-heading">
          <h2>导入批次</h2>
          <span className="muted">{batches.data?.length ?? "—"} 个批次</span>
        </div>
        <ErrorPanel error={batches.error} reload={batches.reload} />
        {!batches.loading && !batches.data?.length ? (
          <EmptyPanel text="还没有导入批次。选择上方文件，建立第一份人才档案。" />
        ) : (
          <Collapse
            ghost
            items={batches.data?.map((batch) => ({
              key: batch.id,
              label: (
                <Space wrap>
                  <strong>{date(batch.created_at)}</strong>
                  <Tag>{batch.items.length} 份文件</Tag>
                  <span className="muted">
                    完成{" "}
                    {
                      batch.items.filter((item) =>
                        [
                          "completed",
                          "success",
                          "succeeded",
                          "indexed",
                          "ready",
                        ].includes(item.status),
                      ).length
                    }{" "}
                    / {batch.items.length}
                  </span>
                  {batch.items.some((item) => item.status === "failed") && (
                    <Tag color="error">有失败文件</Tag>
                  )}
                </Space>
              ),
              children: (
                <Table
                  rowKey="id"
                  size="small"
                  dataSource={batch.items}
                  pagination={
                    batch.items.length > 10 ? { pageSize: 10 } : false
                  }
                  columns={[
                    { title: "文件名", dataIndex: "filename" },
                    {
                      title: "状态",
                      dataIndex: "status",
                      render: (value) => <Status value={value} />,
                    },
                    {
                      title: "处理说明",
                      render: (_, item) =>
                        item.error ? (
                          <span className="error-text">{item.error}</span>
                        ) : item.reused ? (
                          <Tag>已复用已有文件</Tag>
                        ) : (
                          "—"
                        ),
                    },
                  ]}
                />
              ),
            }))}
          />
        )}
      </section>
      <section className="panel">
        <div className="panel-heading">
          <h2>任务队列</h2>
          <span className="muted">失败任务可手动重试</span>
        </div>
        <ErrorPanel error={tasks.error} reload={tasks.reload} />
        <Table
          rowKey="id"
          loading={tasks.loading}
          dataSource={tasks.data}
          locale={{
            emptyText: (
              <EmptyPanel text="暂无任务。导入简历或提交岗位后，任务会显示在这里。" />
            ),
          }}
          scroll={{ x: 700 }}
          pagination={{ pageSize: 10 }}
          columns={[
            {
              title: "任务",
              dataIndex: "kind",
              render: (value) => statusText[value] || value,
            },
            {
              title: "状态",
              dataIndex: "status",
              render: (value) => <Status value={value} />,
            },
            { title: "尝试次数", dataIndex: "attempts", width: 100 },
            { title: "创建时间", dataIndex: "created_at", render: date },
            {
              title: "失败原因",
              dataIndex: "error",
              render: (value) =>
                value ? <span className="error-text">{value}</span> : "—",
            },
            {
              title: "操作",
              render: (_, task) =>
                task.status === "failed" ? (
                  <Button
                    size="small"
                    loading={retrying.includes(task.id)}
                    onClick={() => retry(task.id)}
                  >
                    重试
                  </Button>
                ) : (
                  "—"
                ),
            },
          ]}
        />
      </section>
    </>
  );
}
