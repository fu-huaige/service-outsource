import { beforeEach, describe, expect, it, vi } from "vitest";
import { mount } from "@vue/test-utils";
import { createPinia } from "pinia";
import SimulationView from "../../src/views/SimulationView.vue";

vi.mock("../../src/api/simulation", () => ({ generateSimulationDataset: vi.fn() }));
vi.mock("vue-router", () => ({ useRouter: () => ({ push: vi.fn() }) }));
vi.mock("element-plus", () => ({ ElMessage: { success: vi.fn(), error: vi.fn() } }));

const stubs = {
  "el-form": { template: "<form><slot /></form>" },
  "el-form-item": { props: ["label"], template: "<label>{{ label }}<slot /></label>" },
  "el-radio-group": {
    props: ["modelValue"],
    emits: ["update:modelValue", "change"],
    template: `<div>
      <button type="button" data-test="scenario-s2" @click="$emit('update:modelValue', 'S2'); $emit('change', 'S2')">S2</button>
      <button type="button" data-test="scenario-s3" @click="$emit('update:modelValue', 'S3'); $emit('change', 'S3')">S3</button>
      <slot />
    </div>`,
  },
  "el-radio-button": { template: "<span><slot /></span>" },
  "el-input": {
    props: ["modelValue"],
    emits: ["update:modelValue", "input"],
    template: `<input data-test="dataset-name" :value="modelValue" @input="$emit('update:modelValue', $event.target.value); $emit('input', $event.target.value)" />`,
  },
  "el-input-number": true,
  "el-slider": true,
  "el-button": { template: "<button type='button'><slot /></button>" },
  "el-icon": { template: "<span><slot /></span>" },
  "el-tag": { template: "<span><slot /></span>" },
  "el-descriptions": { template: "<div><slot /></div>" },
  "el-descriptions-item": { template: "<div><slot /></div>" },
  Setting: true,
  Check: true,
  Download: true,
  Cpu: true,
  View: true,
};

const mountView = () => mount(SimulationView, { global: { plugins: [createPinia()], stubs } });
const datasetNameInput = (wrapper: ReturnType<typeof mountView>) =>
  wrapper.get<HTMLInputElement>('[data-test="dataset-name"]');

describe("SimulationView scenario dataset names", () => {
  beforeEach(() => vi.clearAllMocks());

  it("starts with the S1 default dataset name", () => {
    const wrapper = mountView();
    expect(datasetNameInput(wrapper).element.value).toBe("S1_Single_Input_Baseline");
  });

  it("updates the default dataset name when switching to S2", async () => {
    const wrapper = mountView();
    await wrapper.get('[data-test="scenario-s2"]').trigger("click");
    expect(datasetNameInput(wrapper).element.value).toBe("S2_Multi_Input_Delay");
  });

  it("preserves a manually edited dataset name when switching scenarios", async () => {
    const wrapper = mountView();
    await datasetNameInput(wrapper).setValue("Engineer_Custom_Name");
    await wrapper.get('[data-test="scenario-s3"]').trigger("click");
    expect(datasetNameInput(wrapper).element.value).toBe("Engineer_Custom_Name");
  });
});
