import { beforeEach, describe, expect, it, vi } from "vitest";

const { post } = vi.hoisted(() => ({ post: vi.fn() }));

vi.mock("../../src/api/client", () => ({
  default: { post },
}));

import { chatWithCopilot } from "../../src/api/copilot";

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
});
