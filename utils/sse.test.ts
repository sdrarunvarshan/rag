import assert from "node:assert/strict";
import test from "node:test";
import { consumeSseFrames, flushSseBuffer } from "./sse.ts";

test("events split across chunks are reassembled", () => {
  const first = consumeSseFrames('data: {"event":"tok');
  assert.deepEqual(first.events, []);
  const second = consumeSseFrames(`${first.rest}en","text":"hi"}\n\n`);
  assert.deepEqual(second.events, [{ event: "token", text: "hi" }]);
  assert.equal(second.rest, "");
});

test("multiple events in one chunk are all delivered", () => {
  const parsed = consumeSseFrames(
    'data: {"event":"retrieved","sources":[]}\n\ndata: {"event":"token","text":"a"}\n\n',
  );
  assert.equal(parsed.events.length, 2);
  assert.equal(parsed.events[0].event, "retrieved");
  assert.equal(parsed.events[1].text, "a");
});

test("a final incomplete frame is parsed when it is valid and ignored when it is not", () => {
  assert.deepEqual(flushSseBuffer('data: {"event":"done","answer":"ok"}'), [
    { event: "done", answer: "ok" },
  ]);
  assert.deepEqual(flushSseBuffer('data: {"event":'), []);
});
