import { describe, it, expect } from "vitest";
import { analysisData, analysisOption } from "./analysis-chart";

describe("授权分析图表数据校验", () => {
  const result = {
    columns: ["组织", "季度", "人数", "达标率", "课时"],
    rows: [
      ["研发", "Q1", 12, 90, 60],
      ["销售", "Q1", 8, 85, 40],
      ["研发", "Q2", 14, 92, 80],
    ],
  };
  it("识别数值列并保留真实坐标与指标", () => {
    expect(analysisData(result).numeric).toEqual(["人数", "达标率", "课时"]);
    const chart = analysisOption(result, "line", "组织", ["人数"]);
    expect(chart.option?.series[0].data).toEqual([12, 8, 14]);
    expect(chart.option?.xAxis.data).toEqual(["研发", "销售", "研发"]);
  });
  it("饼图拒绝负数，雷达图要求三个指标", () => {
    expect(
      analysisOption(
        { columns: ["名称", "金额"], rows: [["退款", -10]] },
        "pie",
        "名称",
        ["金额"],
      ).reason,
    ).toContain("负值");
    expect(analysisOption(result, "radar", "组织", ["人数"]).reason).toContain(
      "三个",
    );
    expect(
      analysisOption(result, "radar", "组织", ["人数", "达标率", "课时"]).option
        ?.series[0].data[0].value,
    ).toEqual([12, 90, 60]);
  });
  it("热力图保留两维坐标，拒绝重复组合以免误导", () => {
    const chart = analysisOption(result, "heatmap", "组织", ["人数"], "季度");
    expect(chart.option?.series[0].data).toEqual([
      [0, 0, 12],
      [1, 0, 8],
      [0, 1, 14],
    ]);
    expect(
      analysisOption(
        { ...result, rows: [...result.rows, result.rows[0]] },
        "heatmap",
        "组织",
        ["人数"],
        "季度",
      ).reason,
    ).toContain("唯一");
  });
  it("缺失或文本数值不被静默转成零", () => {
    expect(
      analysisData({ columns: ["值"], rows: [[true], [false]] }).numeric,
    ).toEqual([]);
    expect(
      analysisData({ columns: ["值"], rows: [[" "], [4]] }).numeric,
    ).toEqual([]);
    expect(
      analysisData({ columns: ["值"], rows: [[null], [4]] }).numeric,
    ).toEqual([]);
    expect(
      analysisData({ columns: ["值"], rows: [["未知"], [4]] }).numeric,
    ).toEqual([]);
  });
});
