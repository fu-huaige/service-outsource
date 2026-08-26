import { beforeEach, describe, expect, it, vi } from "vitest";

const { post } = vi.hoisted(() => ({ post: vi.fn() }));

vi.mock("../../src/api/client", () => ({
  default: { post },
}));

import { chatWithCopilot, confirmCopilotStep } from "../../src/api/copilot";

describe("Copilot API", () => {
  beforeEach(() => {
    post.mockReset();
    post.mockResolvedValue({});
  });

  it("allows enough time for a real LLM to generate and validate a plan", async () => {
    const request = {
      message: "生成高质量建模数据计划",
      active_version_id: null,
    };

    await chatWithCopilot(request);

    expect(post).toHaveBeenCalledWith("/copilot/chat", request, { timeout: 120_000 });
  });

  it("sends persistent execution and step identifiers when confirming a step", async () => {
    const request = {
      copilot_run_id: "11111111-1111-4111-8111-111111111111",
      confirmation_id: "s2",
      execution_id: "22222222-2222-4222-8222-222222222222",
      step_id: "s2",
      approved: true,
    };

    await confirmCopilotStep(request);

    expect(post).toHaveBeenCalledWith("/copilot/confirm", request);
  });
});
