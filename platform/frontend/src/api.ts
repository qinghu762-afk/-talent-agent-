export type Row = Record<string, any>;
export type Role = "admin" | "hr" | "manager" | "employee";
export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
    public requestId?: string,
  ) {
    super(message);
  }
}
export async function api<T = Row>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const headers = new Headers(options.headers);
  if (options.body && !(options.body instanceof FormData))
    headers.set("Content-Type", "application/json");
  let response: Response;
  try {
    response = await fetch(`/api/v1/${path}`, {
      ...options,
      headers,
      credentials: "include",
    });
  } catch {
    throw new ApiError(0, "无法连接服务，请检查网络后重试");
  }
  let envelope: Row;
  try {
    envelope = await response.json();
  } catch {
    throw new ApiError(response.status, "服务返回异常，请稍后重试");
  }
  if (!response.ok || envelope.code !== "ok")
    throw new ApiError(
      response.status,
      envelope.message || "请求失败，请稍后重试",
      envelope.request_id,
    );
  return envelope.data;
}
export const post = <T = Row>(path: string, data: Row = {}) =>
  api<T>(path, { method: "POST", body: JSON.stringify(data) });
export const patch = (path: string, data: Row) =>
  api(path, { method: "PATCH", body: JSON.stringify(data) });
export const items = (data: any): Row[] =>
  Array.isArray(data?.items) ? data.items : [];
export const pages: Record<
  string,
  { title: string; group: string; roles: Role[]; hint: string }
> = {
  dashboard: {
    title: "工作概览",
    group: "工作台",
    roles: ["admin", "hr", "manager", "employee"],
    hint: "关注待办，推进人才决策与个人成长。",
  },
  talents: {
    title: "人才档案",
    group: "人才运营",
    roles: ["admin", "hr", "manager"],
    hint: "导入履历，核对证据，维护可追溯的人才画像。",
  },
  jobs: {
    title: "岗位与匹配",
    group: "人才运营",
    roles: ["admin", "hr", "manager"],
    hint: "定义岗位要求，通过维度评分和原文证据筛选人才。",
  },
  questions: {
    title: "题库",
    group: "测评与培养",
    roles: ["admin", "hr"],
    hint: "维护客观题与主观题的技能、分值和评分标准。",
  },
  assessments: {
    title: "测评",
    group: "测评与培养",
    roles: ["admin", "hr", "manager", "employee"],
    hint: "发布需经过审批；完成答题后查看能力与改进建议。",
  },
  courses: {
    title: "课程资源",
    group: "测评与培养",
    roles: ["admin", "hr", "manager"],
    hint: "维护技能课程与学习内容。",
  },
  learning: {
    title: "培训与学习",
    group: "测评与培养",
    roles: ["admin", "hr", "manager", "employee"],
    hint: "从能力差距生成培养建议，持续记录学习进度。",
  },
  knowledge: {
    title: "知识库",
    group: "知识与分析",
    roles: ["admin", "hr", "manager", "employee"],
    hint: "管理可访问的知识材料，按组织或个人设置范围。",
  },
  chat: {
    title: "知识助手",
    group: "知识与分析",
    roles: ["admin", "hr", "manager", "employee"],
    hint: "基于有权限的知识回答问题，每条引用均可核对来源。",
  },
  analysis: {
    title: "数据问数",
    group: "知识与分析",
    roles: ["admin", "manager"],
    hint: "自然语言查询授权数据，检查SQL并导出分析报告。",
  },
  approvals: {
    title: "审批待办",
    group: "协作与治理",
    roles: ["admin", "hr", "manager"],
    hint: "核对发布内容，记录审批意见。",
  },
  runs: {
    title: "任务中心",
    group: "协作与治理",
    roles: ["admin", "hr", "manager", "employee"],
    hint: "查看异步任务、进度、版本和失败原因。",
  },
  notifications: {
    title: "通知",
    group: "协作与治理",
    roles: ["admin", "hr", "manager", "employee"],
    hint: "查收工作提醒并标记已读。",
  },
  skills: {
    title: "Skills",
    group: "平台管理",
    roles: ["admin"],
    hint: "维护技能处理器、版本、输入结构与运行参数。",
  },
  automations: {
    title: "定时自动化",
    group: "平台管理",
    roles: ["admin"],
    hint: "按间隔调用已启用的Skill，运行记录进入任务中心。",
  },
  users: {
    title: "账号与组织",
    group: "平台管理",
    roles: ["admin"],
    hint: "管理组织、角色与员工关联，权限由服务端校验。",
  },
  issues: {
    title: "审计与异常",
    group: "平台管理",
    roles: ["admin", "hr"],
    hint: "核查操作记录和处理异常，保留追溯信息。",
  },
  system: {
    title: "系统状态",
    group: "平台管理",
    roles: ["admin"],
    hint: "查看服务连接、模型与运行限制。",
  },
  audits: {
    title: "操作审计",
    group: "平台管理",
    roles: ["admin", "manager"],
    hint: "按组织核对关键操作、操作者与请求编号。",
  },
};
export const visiblePages = (role: Role) =>
  Object.keys(pages).filter((key) => pages[key].roles.includes(role));
export const json = (value: any) => JSON.stringify(value, null, 2);
export const taskId = (response: Row): string | undefined =>
  response.run_id || response.id;
export const deadlineRemaining = (exam: Row, now = Date.now()): number =>
  exam.deadline
    ? Math.max(0, Math.ceil((Date.parse(exam.deadline) - now) / 1000))
    : (exam.duration_minutes || 30) * 60;
export function chartOption(chart: Row | null | undefined): Row | null {
  if (!chart) return null;
  if (chart.option) return chart.option;
  if (chart.series) return chart;
  if (Array.isArray(chart.data))
    return {
      tooltip: { trigger: "axis" },
      grid: { left: 65, right: 20, bottom: 65, top: 24 },
      xAxis: {
        type: "category",
        name: chart.x,
        data: chart.data.map((row: any) =>
          Array.isArray(row) ? row[0] : row[chart.x],
        ),
        axisLabel: { rotate: 20 },
      },
      yAxis: { type: "value", name: chart.y },
      series: [
        {
          name: chart.y,
          type: chart.type === "line" ? "line" : "bar",
          data: chart.data.map((row: any) =>
            Array.isArray(row) ? row[1] : row[chart.y],
          ),
        },
      ],
    };
  return null;
}
export const label = (row: Row) =>
  row.title || row.name || row.profile?.name || row.username || row.id;
export const statusNames: Record<string, string> = {
  pending: "待处理",
  queued: "排队中",
  running: "进行中",
  completed: "已完成",
  succeeded: "已完成",
  failed: "失败",
  cancelled: "已取消",
  draft: "草稿",
  published: "已发布",
  approved: "已批准",
  rejected: "已驳回",
  submitted: "已提交",
  in_progress: "进行中",
  active: "进行中",
  ready: "可用",
  indexing: "索引中",
  inactive: "停用",
  started: "答题中",
  waiting_approval: "待审批",
  rated: "已评级",
  review_required: "待复核",
  learning: "学习中",
  assigned: "已分配",
  ok: "正常",
  unavailable: "不可用",
  error: "异常",
};
