import { describe, expect, it } from "vitest";
import { SSEBuffer } from "./api";

const frame = (obj: unknown) => `data: ${JSON.stringify(obj)}\n\n`;

describe("SSEBuffer", () => {
  it("parses a whole frame", () => {
    const sse = new SSEBuffer();
    expect(sse.push(frame({ type: "status", stage: "generating" }))).toEqual([
      { type: "status", stage: "generating" },
    ]);
  });

  it("returns multiple frames from one chunk", () => {
    const sse = new SSEBuffer();
    const chunk = frame({ type: "status", stage: "validating" }) +
      frame({ type: "status", stage: "executing" });
    expect(sse.push(chunk).map((e) => (e as { stage: string }).stage)).toEqual([
      "validating",
      "executing",
    ]);
  });

  it("reassembles a frame split across chunks", () => {
    const sse = new SSEBuffer();
    const full = frame({ type: "result", summary: "hi", rows: [[1]] });
    const mid = Math.floor(full.length / 2);
    expect(sse.push(full.slice(0, mid))).toEqual([]); // nothing complete yet
    const events = sse.push(full.slice(mid));
    expect(events).toHaveLength(1);
    expect((events[0] as { summary: string }).summary).toBe("hi");
  });

  it("waits for the frame delimiter before emitting", () => {
    const sse = new SSEBuffer();
    expect(sse.push("data: {\"type\":\"status\",\"stage\":\"executing\"}")).toEqual([]);
    expect(sse.push("\n\n")).toHaveLength(1);
  });

  it("ignores non-data lines", () => {
    const sse = new SSEBuffer();
    expect(sse.push(": keep-alive\n\n")).toEqual([]);
  });
});
