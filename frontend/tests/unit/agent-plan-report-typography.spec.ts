import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";
import AgentPlan from "../../src/components/workspace/AgentPlan.vue";
import ToolExecution from "../../src/components/workspace/ToolExecution.vue";
import type { CopilotExecutionStepSnapshot, ExecutionPlanStep } from "../../src/types/api";

const step = (stepId: string, tool: string): ExecutionPlanStep => ({
  step_id: stepId,
  tool,
  depends_on: [],
  parameters: {},
  requires_confirmation: false,
  status: "pending",
});

const stepRun = (stepId: string, tool: string): CopilotExecutionStepSnapshot => ({
  step_id: stepId,
  sequence: 1,
  tool,
  status: "completed",
  requires_confirmation: false,
  confirmation_status: "NOT_REQUIRED",
  attempt_count: 1,
  source_version_id: null,
  result_version_id: null,
  input_payload: {},
  result_payload: {},
  processing_run_ids: [],
  error_code: null,
  error_message: null,
  started_at: null,
  finished_at: null,
});

describe("AgentPlan report typography", () => {
  it("uses Chinese Sans only for the approved report step and preserves other technical steps", () => {
    const wrapper = mount(AgentPlan, {
      props: {
        steps: [
          step("step-profile", "profile_dataset"),
          step("step-report", "generate_report"),
        ],
        stepRuns: [],
        currentStepId: null,
      },
    });
    const labels = wrapper.findAll(".plan-step__tool");

    expect(labels[0]!.text()).toBe("profile_dataset");
    expect(labels[0]!.classes()).toContain("font-mono");
    expect(labels[1]!.text()).toBe("报告交付");
    expect(labels[1]!.text()).not.toContain("(Report)");
    expect(labels[1]!.classes()).not.toContain("font-mono");
    expect(labels[1]!.classes()).toContain("plan-step__tool--report");

    const source = readFileSync(resolve(process.cwd(), "src/components/workspace/AgentPlan.vue"), "utf8");
    const reportRule = source.match(/\.plan-step__tool--report\s*\{([^}]+)\}/)?.[1] ?? "";
    expect(reportRule).toContain("font-family: var(--font-sans)");
    expect(reportRule).toContain("letter-spacing: normal");
  });

  it("normalizes the real execution-stream report label by stable tool key", () => {
    const report = mount(ToolExecution, {
      props: {
        stepRun: stepRun("step-report", "generate_report"),
        planStep: step("step-report", "generate_report"),
      },
    });
    const reportLabel = report.get(".te-tool");

    expect(reportLabel.text()).toBe("报告交付");
    expect(reportLabel.text()).not.toContain("Report");
    expect(reportLabel.classes()).toContain("te-tool--report");
    expect(reportLabel.classes()).not.toContain("font-mono");

    const technical = mount(ToolExecution, {
      props: {
        stepRun: stepRun("step-clean", "clean"),
        planStep: step("step-clean", "clean"),
      },
    });
    expect(technical.get(".te-tool").text()).toBe("数据清洗 (Clean)");
    expect(technical.get(".te-tool").classes()).toContain("font-mono");

    const source = readFileSync(resolve(process.cwd(), "src/components/workspace/ToolExecution.vue"), "utf8");
    expect(source).toContain("generate_report: '报告交付'");
    expect(source).not.toContain("generate_report: '报告交付 (Report)'");
    const reportRule = source.match(/\.te-tool--report\s*\{([^}]+)\}/)?.[1] ?? "";
    expect(reportRule).toContain("font-family: var(--font-sans)");
    expect(reportRule).toContain("letter-spacing: normal");
  });
});
