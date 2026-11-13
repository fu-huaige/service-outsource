import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";
import ExperimentSpecFields from "../../src/components/composer/ExperimentSpecFields.vue";
import type { DatasetVersionNode } from "../../src/types/api";

const version: DatasetVersionNode = {
  id: "selected-version", name: "V2", tool: "cleaning", created_at: "2026-01-01",
  row_count: 250, column_count: 4, artifact_path: "version.csv",
  sha256: "a".repeat(64), input_columns: ["u1", "u2"], output_column: "y",
  time_column: "timestamp",
};

function form(source = version) {
  return mount(ExperimentSpecFields, { props: { datasetId: "dataset", version: source } });
}

async function fill(wrapper: ReturnType<typeof form>) {
  const inputs = wrapper.findAll('[data-test="modeling-input"]');
  await inputs[1]!.setValue(true);
  await inputs[0]!.setValue(true);
  for (const [field, value] of Object.entries({
    continuous: "0-150, 150-250", train: "0-100", validation: "100-150", test: "150-250",
  })) await wrapper.get('[data-test="modeling-' + field + '"]').setValue(value);
}

const lastRequest = (wrapper: ReturnType<typeof form>) => wrapper.emitted("change")?.at(-1)?.[0];

describe("Agent experiment contract", () => {
  it("preserves ordered columns, exact SHA and explicit half-open ranges", async () => {
    const wrapper = form();
    expect(lastRequest(wrapper)).toBeNull();
    await fill(wrapper);
    expect(lastRequest(wrapper)).toMatchObject({
      experiment_spec: {
        dataset_id: "dataset", dataset_version_id: version.id, dataset_version_sha256: version.sha256,
        target_column: "y", input_columns: ["u2", "u1"], training_selection: { mode: "full_train" },
        split: {
          train: [{ start: 0, stop: 100 }],
          validation: [{ start: 100, stop: 150 }],
          test: [{ start: 150, stop: 250 }],
        },
        continuous_runs: [{ start: 0, stop: 150 }, { start: 150, stop: 250 }],
      },
    });
    const validation = wrapper.get('[data-test="modeling-validation"]');
    await validation.setValue("100-151");
    expect(validation.attributes("aria-invalid")).toBe("true");
    expect(lastRequest(wrapper)).toBeNull();
    await wrapper.get('[data-test="modeling-test"]').setValue("151-250");
    expect(lastRequest(wrapper)).toBeNull();
    expect(wrapper.text()).toContain("完整落在一个连续区段");
    await validation.setValue("100-150");
    expect(validation.attributes("aria-invalid")).toBe("false");
    expect(lastRequest(wrapper)).not.toBeNull();
    wrapper.unmount();
  });

  it("updates the target row and preserves the order of eligible input selections", async () => {
    const wrapper = form();
    await fill(wrapper);
    wrapper.getComponent('[data-test="modeling-goal"]').vm.$emit("update:modelValue", "nonlinear_regression");
    wrapper.getComponent('[data-test="modeling-target"]').vm.$emit("update:modelValue", "u2");
    await wrapper.vm.$nextTick();

    const inputs = wrapper.findAll('[data-test="modeling-input"]');
    expect(inputs[1]!.attributes("disabled")).toBeDefined();
    expect(inputs[1]!.element).toHaveProperty("checked", false);
    expect(inputs[1]!.element.closest("label")?.textContent).toContain("目标变量");
    expect(lastRequest(wrapper)).toMatchObject({
      goal: "nonlinear_regression",
      experiment_spec: { target_column: "u2", input_columns: ["u1"] },
    });
    await inputs[2]!.setValue(true);
    await inputs[0]!.setValue(false);
    await inputs[0]!.setValue(true);
    expect(lastRequest(wrapper)).toMatchObject({ experiment_spec: { input_columns: ["y", "u1"] } });
    expect(wrapper.text()).toContain("已选 2 项");
    wrapper.unmount();
  });

  it("blocks versions without a trusted digest", async () => {
    const wrapper = form({ ...version, sha256: null });
    await fill(wrapper);
    expect(lastRequest(wrapper)).toBeNull();
    expect(wrapper.text()).toContain("缺少可信 CSV SHA-256");
    wrapper.unmount();
  });

  it("keeps the public horizon fixed while validating the TimeXer horizon", async () => {
    const wrapper = form();
    await fill(wrapper);
    await wrapper.get('[data-test="modeling-forecast"]').setValue(true);
    expect(lastRequest(wrapper)).toBeNull();
    wrapper.getComponent('[data-test="modeling-sampling"]').vm.$emit("update:modelValue", "uniform");
    await wrapper.vm.$nextTick();
    for (const [field, value] of Object.entries({
      period: "1", target_window_length: "32",
      exogenous_window_length: "16", prediction_length: "33",
    })) await wrapper.get('[data-test="modeling-' + field + '"]').setValue(value);
    expect(lastRequest(wrapper)).toBeNull();
    await wrapper.get('[data-test="modeling-prediction_length"]').setValue("3");
    expect(lastRequest(wrapper)).toMatchObject({
      experiment_spec: {
        time_axis: { column: "timestamp", sample_period_seconds: 1, sampling_status: "uniform" },
        feature_spec: { prediction_horizon: 1 },
      },
      forecast_spec: { target_window_length: 32, exogenous_window_length: 16, prediction_length: 3 },
    });
    wrapper.unmount();
  });
});
