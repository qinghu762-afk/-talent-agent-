export type Field = {
  name: string;
  label: string;
  type?:
    | "text"
    | "textarea"
    | "number"
    | "list"
    | "json"
    | "boolean"
    | "select"
    | "password";
  options?: string[];
  required?: boolean;
  help?: string;
  defaultValue?: any;
  when?: { field: string; value: string };
  min?: number;
};
export type Schema = { title: string; fields: Field[]; readonly?: boolean };
const f = (
  name: string,
  label: string,
  type: Field["type"] = "text",
  required = false,
  help?: string,
): Field => ({ name, label, type, required, help });
export const schemas: Record<string, Schema> = {
  organizations: {
    title: "组织",
    fields: [f("name", "组织名称", "text", true)],
  },
  users: {
    title: "账号",
    fields: [
      f("username", "账号", "text", true),
      f(
        "password",
        "密码",
        "password",
        false,
        "新建必填；编辑留空保留当前密码",
      ),
      {
        name: "role",
        label: "角色",
        type: "select",
        options: ["admin", "hr", "manager", "employee"],
        required: true,
      },
      f(
        "role_template_id",
        "角色模板",
        "text",
        false,
        "选用模板后，基础角色由模板决定；留空使用上方基础角色。",
      ),
      f("org_id", "所属组织", "text", true),
      f("talent_id", "关联人才"),
    ],
  },
  roles: {
    title: "角色模板",
    fields: [
      f("name", "模板名称", "text", true),
      {
        name: "base_role",
        label: "基础角色",
        type: "select",
        options: ["admin", "hr", "manager", "employee"],
        required: true,
      },
      f(
        "permissions",
        "允许操作",
        "list",
        true,
        "仅允许已选择的操作，且不能超出基础角色权限；可添加 METHOD:资源名 格式的自定义操作。",
      ),
      f(
        "denied_fields",
        "隐藏字段",
        "list",
        false,
        "对该角色隐藏的敏感字段，可添加字段名称。",
      ),
      {
        name: "data_scope",
        label: "数据范围",
        type: "select",
        options: ["org", "self"],
        required: true,
        defaultValue: "org",
      },
    ],
  },
  talents: {
    title: "人才档案",
    fields: [
      f(
        "profile",
        "人才画像",
        "json",
        true,
        "填写包含 name、skills、experiences、education 等字段的JSON",
      ),
    ],
  },
  jobs: {
    title: "岗位",
    fields: [
      f("title", "岗位名称", "text", true),
      f("description", "岗位描述", "textarea", true),
      f(
        "requirements",
        "岗位要求",
        "json",
        false,
        "required_skills / preferred_skills 数组；min_experience_months 数字；min_education / location 字符串。留空将由模型解析。",
      ),
    ],
  },
  questions: {
    title: "题目",
    fields: [
      f("title", "题干", "textarea", true),
      {
        name: "question_type",
        label: "题型",
        type: "select",
        options: ["single", "multiple", "text"],
        required: true,
      },
      f("options", "选项", "list", false, "每行一个选项；答题值使用选项原文"),
      f(
        "answer",
        "标准答案",
        "json",
        true,
        "单选与文本使用JSON字符串，多选使用数组",
      ),
      f("rubric", "评分标准", "textarea"),
      f("skills", "技能", "list"),
      f("points", "分值", "number", true),
    ],
  },
  assessments: {
    title: "测评",
    fields: [
      f("title", "测评名称", "text", true),
      f("talent_id", "参测人才", "text", true),
      f("question_ids", "题目", "list", true),
      f("duration_minutes", "时长（分钟）", "number", true),
    ],
  },
  courses: {
    title: "课程",
    fields: [
      f("title", "课程名称", "text", true),
      f("content", "课程内容", "textarea", true),
      f("skills", "覆盖技能", "list"),
      f("duration_seconds", "课程时长（秒）", "number", true),
      f("quiz", "课程练习", "json"),
    ],
  },
  "training-plans": {
    title: "培训计划",
    fields: [
      f("title", "计划名称", "text", true),
      f("talent_id", "参训人才", "text", true),
      f("course_ids", "课程", "list", true),
    ],
  },
  skills: {
    title: "Skill",
    fields: [
      f("name", "名称", "text", true),
      f("version", "版本", "text", true),
      f("handler", "处理器", "text", true),
      f("input_schema", "输入结构", "json"),
      f("config", "配置", "json"),
      f("enabled", "启用", "boolean"),
    ],
  },
  automations: {
    title: "自动化",
    fields: [
      f("name", "名称", "text", true),
      f("skill_id", "关联Skill", "text", true),
      {
        name: "trigger",
        label: "触发方式",
        type: "select",
        options: ["schedule", "event"],
        required: true,
        defaultValue: "schedule",
      },
      {
        name: "event_kind",
        label: "业务事件",
        type: "select",
        options: ["resume", "assessment", "training", "job"],
        required: true,
        when: { field: "trigger", value: "event" },
      },
      f(
        "parameters",
        "执行参数",
        "json",
        false,
        '事件触发可引用事件字段，例如 {"talent_id":"$event.talent_id"}。',
      ),
      {
        name: "interval_seconds",
        label: "执行间隔（秒）",
        type: "number",
        required: true,
        min: 60,
        defaultValue: 3600,
        when: { field: "trigger", value: "schedule" },
      },
      f("enabled", "启用", "boolean"),
    ],
  },
  notifications: { title: "通知", readonly: true, fields: [] },
  approvals: { title: "审批", readonly: true, fields: [] },
  runs: { title: "任务", readonly: true, fields: [] },
  issues: { title: "审计与异常", readonly: true, fields: [] },
  audits: { title: "审计记录", readonly: true, fields: [] },
  knowledge: { title: "知识", readonly: true, fields: [] },
};
