import { Alert, Button, Empty, Form, Select, Tag, Typography } from "antd";
import type { Evidence } from "./types";
export const statusText: Record<string, string> = {
  queued: "排队中",
  dispatched: "已调度",
  retry: "重试中",
  job: "岗位解析",
  pending: "待处理",
  running: "处理中",
  processing: "处理中",
  parsing: "解析中",
  indexing: "索引中",
  retrying: "重试中",
  completed: "已完成",
  succeeded: "已完成",
  success: "已完成",
  ready: "可使用",
  indexed: "已索引",
  failed: "失败",
  cancelled: "已取消",
  conflict: "待核对",
  duplicate: "疑似重复",
  identity_conflict: "身份冲突",
  semantic_duplicate: "疑似重复",
  anomaly: "信息异常",
  parse: "档案解析",
  match: "岗位匹配",
  index: "档案索引",
  job_parse: "岗位解析",
  ingest: "文件入库",
};
export function Status({ value }: { value: string }) {
  const color = ["failed", "conflict"].includes(value)
    ? "error"
    : ["completed", "succeeded", "success", "ready", "indexed"].includes(value)
      ? "success"
      : ["queued", "dispatched", "pending", "retry", "retrying"].includes(value)
        ? "warning"
        : "processing";
  return <Tag color={color}>{statusText[value] || value}</Tag>;
}
export function ErrorPanel({
  error,
  reload,
}: {
  error: string;
  reload?: () => void;
}) {
  return error ? (
    <Alert
      type="error"
      showIcon
      message={error}
      action={
        reload ? (
          <Button size="small" onClick={reload}>
            重新加载
          </Button>
        ) : undefined
      }
    />
  ) : null;
}
export function EmptyPanel({
  text,
  action,
}: {
  text: string;
  action?: React.ReactNode;
}) {
  return (
    <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={text}>
      {action}
    </Empty>
  );
}
export const date = (value: string) =>
  value ? new Date(value).toLocaleString("zh-CN", { hour12: false }) : "—";
export const display = (value: unknown): string =>
  value === null || value === undefined || value === ""
    ? "未提供"
    : typeof value === "string"
      ? value
      : JSON.stringify(value, null, 2);
export function TagsField({ name, label }: { name: string; label: string }) {
  return (
    <Form.Item name={name} label={label}>
      <Select
        mode="tags"
        tokenSeparators={["，", ","]}
        open={false}
        placeholder="输入后按回车添加"
      />
    </Form.Item>
  );
}
const evidenceLabels: Record<string, string> = {
  name: "姓名",
  phone: "电话",
  email: "邮箱",
  location: "所在地",
  education: "教育经历",
  experiences: "工作经历",
  projects: "项目经历",
  skills: "技能",
  certificates: "证书",
  intentions: "求职意向",
  summary: "摘要",
  required_skills: "必备技能",
  preferred_skills: "加分技能",
  min_experience_months: "最低工作月数",
  min_education: "最低学历",
  required_certificates: "必需证书",
  responsibilities: "工作职责",
};
export function EvidenceList({
  evidence,
}: {
  evidence: Record<string, Evidence[]>;
}) {
  const entries = Object.entries(evidence || {});
  return entries.length ? (
    <div className="evidence-list">
      {entries.map(([field, quotes]) => (
        <section key={field}>
          <strong>{evidenceLabels[field] || field}</strong>
          {quotes.map((entry, i) => (
            <blockquote key={i}>
              {entry.quote}
              <footer>
                {entry.page ? `第 ${entry.page} 页` : "原始文件"}
                {entry.start !== undefined && entry.start !== null
                  ? ` · 字符位置 ${entry.start}`
                  : ""}
                {entry.source_id && (
                  <> · <a href={`/api/v1/documents/${encodeURIComponent(entry.source_id)}/file`}>下载来源文件</a></>
                )}
              </footer>
            </blockquote>
          ))}
        </section>
      ))}
    </div>
  ) : (
    <Typography.Text type="secondary">尚无可展示的原文依据</Typography.Text>
  );
}
