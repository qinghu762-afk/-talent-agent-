import type { Row } from "./api";

export type AnalysisChartType = "bar" | "line" | "pie" | "radar" | "heatmap";
export const chartTypes = [
  { value: "bar", label: "柱状图" },
  { value: "line", label: "折线图" },
  { value: "pie", label: "饼图" },
  { value: "radar", label: "雷达图" },
  { value: "heatmap", label: "热力图" },
];
export function analysisData(result: Row) {
  const columns: string[] = Array.isArray(result.columns) ? result.columns : [];
  const rows: Row[] = (result.rows || []).map((row: any) =>
    Array.isArray(row)
      ? Object.fromEntries(columns.map((key, i) => [key, row[i]]))
      : row,
  );
  const numeric = columns.filter(
    (key) =>
      rows.some((row) => row[key] != null && row[key] !== "") &&
      rows.every(
        (row) =>
          row[key] != null &&
          (typeof row[key] === "number" ||
            (typeof row[key] === "string" && row[key].trim() !== "")) &&
          Number.isFinite(Number(row[key])),
      ),
  );
  return {
    columns,
    rows,
    numeric,
    categories: columns.filter((key) => !numeric.includes(key)),
  };
}
export function analysisOption(
  result: Row,
  type: AnalysisChartType,
  dimension: string,
  metrics: string[],
  secondDimension?: string,
): { option?: Row; reason?: string } {
  const { rows, numeric } = analysisData(result);
  if (!rows.length) return { reason: "本次查询没有数据，请调整问题后重试。" };
  if (!metrics.length || metrics.some((key) => !numeric.includes(key)))
    return {
      reason: "请至少选择一个完整的数值指标；含空值或非数值的列不作为指标。",
    };
  if (!dimension) return { reason: "请选择分类维度。" };
  const sliced = rows.slice(0, 50),
    labels = sliced.map((row) => String(row[dimension] ?? "未提供"));
  const tooltip = {
    trigger: type === "bar" || type === "line" ? "axis" : "item",
  };
  if (type === "pie") {
    if (rows.some((row) => Number(row[metrics[0]]) < 0))
      return { reason: "饼图需要非负指标，当前指标含负值。" };
    if (!rows.some((row) => Number(row[metrics[0]]) > 0))
      return { reason: "饼图需要至少一个大于零的数值。" };
    return {
      option: {
        tooltip,
        legend: { type: "scroll", bottom: 0 },
        series: [
          {
            type: "pie",
            radius: ["25%", "65%"],
            data: sliced.map((row, i) => ({
              name: labels[i],
              value: Number(row[metrics[0]]),
            })),
          },
        ],
      },
    };
  }
  if (type === "radar") {
    if (metrics.length < 3)
      return { reason: "雷达图需要至少三个数值指标，请增加指标选择。" };
    return {
      option: {
        tooltip,
        legend: { type: "scroll", bottom: 0 },
        radar: {
          indicator: metrics.map((key) => ({
            name: key,
            min: Math.min(0, ...rows.map((row) => Number(row[key]))),
            max: Math.max(1, ...rows.map((row) => Number(row[key]))) * 1.1,
          })),
        },
        series: [
          {
            type: "radar",
            data: sliced.slice(0, 10).map((row, i) => ({
              name: labels[i],
              value: metrics.map((key) => Number(row[key])),
            })),
          },
        ],
      },
    };
  }
  if (type === "heatmap") {
    if (!secondDimension || secondDimension === dimension)
      return { reason: "热力图需要两个不同的分类维度和一个数值指标。" };
    const x = [
        ...new Set(rows.map((row) => String(row[dimension] ?? "未提供"))),
      ],
      y = [
        ...new Set(rows.map((row) => String(row[secondDimension] ?? "未提供"))),
      ];
    const seen = new Set<string>();
    if (
      rows.some((row) => {
        const pair = JSON.stringify([row[dimension], row[secondDimension]]);
        if (seen.has(pair)) return true;
        seen.add(pair);
        return false;
      })
    )
      return {
        reason: "热力图每个维度组合需要唯一一行，请在查询中先按两个维度聚合。",
      };
    const data = rows
      .slice(0, 500)
      .map((row) => [
        x.indexOf(String(row[dimension] ?? "未提供")),
        y.indexOf(String(row[secondDimension] ?? "未提供")),
        Number(row[metrics[0]]),
      ]);
    const min = Math.min(...data.map((row) => row[2])),
      max = Math.max(...data.map((row) => row[2]));
    return {
      option: {
        tooltip,
        grid: { left: 80, right: 30, top: 30, bottom: 90 },
        xAxis: {
          type: "category",
          name: dimension,
          data: x,
          axisLabel: { rotate: 20 },
        },
        yAxis: { type: "category", name: secondDimension, data: y },
        visualMap: {
          min,
          max: max === min ? max + 1 : max,
          calculable: true,
          orient: "horizontal",
          left: "center",
          bottom: 0,
          inRange: { color: ["#edf4f8", "#8cb6cc", "#195b82"] },
        },
        series: [
          { name: metrics[0], type: "heatmap", data, label: { show: true } },
        ],
      },
    };
  }
  return {
    option: {
      tooltip,
      legend: { type: "scroll", bottom: 0 },
      grid: { left: 70, right: 30, bottom: 85, top: 40 },
      xAxis: {
        type: "category",
        name: dimension,
        data: labels,
        axisLabel: { rotate: 20 },
      },
      yAxis: { type: "value" },
      series: metrics.map((key) => ({
        name: key,
        type,
        data: sliced.map((row) => Number(row[key])),
      })),
    },
  };
}
