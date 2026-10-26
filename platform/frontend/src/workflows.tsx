import { useState } from "react";
import {
  Alert,
  Button,
  Checkbox,
  Form,
  Input,
  InputNumber,
  Modal,
  Radio,
  Select,
  Spin,
  Upload,
} from "antd";
import { api, items, label, post, type Row } from "./api";
import { Chart, Detail, Failure, useResource } from "./components";

export function TalentSearch({ onRun }: { onRun: (id: string) => void }) {
  const [busy, setBusy] = useState(false),
    [error, setError] = useState<unknown>();
  return (
    <section className="surface top-space">
      <h3>按需求检索人才</h3>
      <Form
        layout="inline"
        onFinish={async ({ query }) => {
          setBusy(true);
          setError(undefined);
          try {
            onRun((await post("talents/search", { query })).id);
          } catch (e) {
            setError(e);
          } finally {
            setBusy(false);
          }
        }}
      >
        <Form.Item
          name="query"
          rules={[{ required: true, message: "请填写人才需求" }]}
        >
          <Input
            aria-label="人才检索需求"
            placeholder="例如：有Python和制造业项目经验的人才"
            style={{ width: 360, maxWidth: "100%" }}
          />
        </Form.Item>
        <Button htmlType="submit" loading={busy}>
          智能检索
        </Button>
      </Form>
      {!!error && <Failure error={error} />}
    </section>
  );
}

export function JobImport({
  onClose,
  onRun,
}: {
  onClose: () => void;
  onRun: (id: string) => void;
}) {
  const [file, setFile] = useState<File>(),
    [busy, setBusy] = useState(false),
    [error, setError] = useState<unknown>(),
    [form] = Form.useForm();
  return (
    <Modal
      open
      title="从文件导入岗位"
      okText="上传并解析岗位"
      cancelText="取消"
      onCancel={onClose}
      onOk={() => form.submit()}
      confirmLoading={busy}
    >
      {!!error && <Failure error={error} />}
      <Form
        form={form}
        layout="vertical"
        onFinish={async (values) => {
          setBusy(true);
          setError(undefined);
          try {
            if (!file) throw new Error("请选择岗位文件");
            const body = new FormData();
            body.append("file", file);
            body.append("title", values.title);
            const run = await api("jobs/import", { method: "POST", body });
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
          name="title"
          label="岗位名称"
          rules={[{ required: true, message: "请填写岗位名称" }]}
        >
          <Input />
        </Form.Item>
        <Form.Item label="岗位文件">
          <Upload.Dragger
            maxCount={1}
            beforeUpload={() => false}
            accept=".pdf,.doc,.docx,.txt,.md,.html,.png,.jpg,.jpeg"
            onChange={({ fileList }) =>
              setFile(fileList[0]?.originFileObj as File)
            }
          >
            <p>点击选择或拖入岗位说明文件</p>
          </Upload.Dragger>
        </Form.Item>
      </Form>
    </Modal>
  );
}

export function Growth({ id }: { id: string }) {
  const { data, error, loading, reload } = useResource(`talents/${id}/growth`);
  if (error) return <Failure error={error} retry={reload} />;
  if (loading) return <Spin />;
  return (
    <section>
      <h3>能力与学习成长</h3>
      {!!data.trend?.length && (
        <Chart
          label="历次测评分数趋势"
          option={{
            tooltip: { trigger: "axis" },
            xAxis: {
              type: "category",
              data: data.trend.map((x: Row) =>
                new Date(x.at).toLocaleDateString("zh-CN"),
              ),
            },
            yAxis: { type: "value", min: 0, max: 100 },
            series: [
              { type: "line", data: data.trend.map((x: Row) => x.total) },
            ],
          }}
        />
      )}
      <h4>测评记录</h4>
      <Detail value={data.assessments} />
      <h4>培养计划</h4>
      <Detail value={data.plans} />
      <details>
        <summary>学习事件记录</summary>
        <Detail value={data.events} />
      </details>
    </section>
  );
}

export function ComposeAssessment({
  onClose,
  onSaved,
}: {
  onClose: () => void;
  onSaved: () => void;
}) {
  const talents = useResource("talents"),
    jobs = useResource("jobs");
  const [form] = Form.useForm(),
    [busy, setBusy] = useState(false),
    [error, setError] = useState<unknown>();
  return (
    <Modal
      open
      title="按人才或岗位自动组卷"
      okText="生成测评草稿"
      cancelText="取消"
      onCancel={onClose}
      onOk={() => form.submit()}
      confirmLoading={busy}
    >
      <Alert
        type="info"
        message="按技能优先选择题库中的题目，生成后仍需提交发布审批。"
      />
      {!!(talents.error || jobs.error) && (
        <Failure error={talents.error || jobs.error} />
      )}
      {!!error && <Failure error={error} />}
      <Form
        form={form}
        layout="vertical"
        initialValues={{ question_count: 10, duration_minutes: 30 }}
        onFinish={async (values) => {
          setBusy(true);
          setError(undefined);
          try {
            await post("assessments/compose", values);
            onSaved();
            onClose();
          } catch (e) {
            setError(e);
          } finally {
            setBusy(false);
          }
        }}
      >
        <Form.Item
          name="title"
          label="测评名称"
          rules={[{ required: true, message: "请填写测评名称" }]}
        >
          <Input />
        </Form.Item>
        <Form.Item
          name="talent_id"
          label="参测人才"
          rules={[{ required: true, message: "请选择参测人才" }]}
        >
          <Select
            showSearch
            optionFilterProp="label"
            loading={talents.loading}
            options={items(talents.data).map((x) => ({
              value: x.id,
              label: label(x),
            }))}
          />
        </Form.Item>
        <Form.Item name="job_id" label="参考岗位（可选）">
          <Select
            allowClear
            showSearch
            optionFilterProp="label"
            loading={jobs.loading}
            options={items(jobs.data).map((x) => ({
              value: x.id,
              label: label(x),
            }))}
          />
        </Form.Item>
        <Form.Item
          name="question_count"
          label="题目数量"
          rules={[{ required: true, message: "请填写题目数量" }]}
        >
          <InputNumber min={1} max={100} />
        </Form.Item>
        <Form.Item
          name="duration_minutes"
          label="时长（分钟）"
          rules={[{ required: true, message: "请填写时长" }]}
        >
          <InputNumber min={1} max={180} />
        </Form.Item>
      </Form>
    </Modal>
  );
}

export function CourseQuiz({
  plan,
  course,
  onSaved,
}: {
  plan: Row;
  course: Row;
  onSaved: () => void;
}) {
  const [answers, setAnswers] = useState<Row>({}),
    [result, setResult] = useState<Row>(),
    [busy, setBusy] = useState(false),
    [error, setError] = useState<unknown>();
  if (!course.quiz?.length) return null;
  const completed = plan.progress?.[course.id]?.completed;
  return (
    <section className="top-space">
      <h3>课程考核</h3>
      {!completed && (
        <Alert type="info" message="完成课程并保存有效进度后，可提交考核。" />
      )}
      {course.quiz.map((q: Row, i: number) => (
        <section key={q.id}>
          <h4>
            {i + 1}. {q.title}
          </h4>
          {q.question_type === "multiple" ? (
            <Checkbox.Group
              options={q.options}
              value={answers[q.id] || []}
              onChange={(value) => setAnswers({ ...answers, [q.id]: value })}
            />
          ) : (
            <Radio.Group
              options={q.options}
              value={answers[q.id]}
              onChange={(e) =>
                setAnswers({ ...answers, [q.id]: e.target.value })
              }
            />
          )}
        </section>
      ))}
      <Button
        className="top-space"
        loading={busy}
        disabled={!completed}
        onClick={async () => {
          setBusy(true);
          setError(undefined);
          try {
            setResult(
              await post(`training-plans/${plan.id}/quiz`, {
                course_id: course.id,
                answers,
              }),
            );
            onSaved();
          } catch (e) {
            setError(e);
          } finally {
            setBusy(false);
          }
        }}
      >
        提交课程考核
      </Button>
      {!!error && <Failure error={error} />}
      {result && (
        <Alert
          className="top-space"
          type={result.passed ? "success" : "warning"}
          message={`${result.score} 分 · ${result.passed ? "通过" : "未通过"}（及格 ${result.threshold} 分，第 ${result.attempt} 次）`}
        />
      )}
    </section>
  );
}
