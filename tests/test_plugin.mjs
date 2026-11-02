import assert from "node:assert/strict";
import test from "node:test";
import { apply, inject, name } from "../index.js";

test("registers the packaged delivery-video skill with a usable resource root", () => {
  const registered = [];
  const dispose = () => {};

  const result = apply({
    skills: {
      register(skill) {
        registered.push(skill);
        return dispose;
      },
    },
  });

  assert.equal(name, "delivery-video");
  assert.deepEqual(inject, ["skills"]);
  assert.equal(result, dispose);
  assert.equal(registered.length, 1);
  assert.equal(registered[0].name, "delivery-video");
  assert.match(registered[0].description, /delivery\/acceptance demo videos/);
  assert.match(registered[0].content, /^# Delivery Video/m);
  assert.equal(registered[0].content.includes("\nname: delivery-video\n"), false);
  assert.equal(registered[0].resourceBase.kind, "directory");
  assert.match(registered[0].resourceBase.path, /skills\/$/);
  assert.deepEqual(registered[0].invocation, {
    modelInvocable: true,
    userInvocable: true,
  });
});
