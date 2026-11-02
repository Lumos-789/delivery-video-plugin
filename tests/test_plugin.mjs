import assert from "node:assert/strict";
import test from "node:test";
import { apply, inject, name } from "../index.js";

function createAgent(registrations) {
  const ctx = {
    skills: {
      register(skill) {
        const registration = { skill, disposed: 0 };
        registrations.push(registration);
        return () => {
          registration.disposed += 1;
        };
      },
    },
    effect(factory) {
      return factory();
    },
  };
  return { ctx };
}

function createHarness(agents = []) {
  const hostRegistrations = [];
  const listeners = new Map();
  const cleanups = [];
  const context = {
    skills: {
      register(skill) {
        hostRegistrations.push(skill);
      },
    },
    agents: {
      list() {
        return [...agents];
      },
    },
    on(event, listener) {
      const eventListeners = listeners.get(event) ?? [];
      eventListeners.push(listener);
      listeners.set(event, eventListeners);
      return () => {
        listeners.set(
          event,
          (listeners.get(event) ?? []).filter((item) => item !== listener),
        );
      };
    },
    effect(factory) {
      const dispose = factory();
      cleanups.push(dispose);
      return dispose;
    },
  };

  return {
    context,
    hostRegistrations,
    emit(event, payload) {
      for (const listener of listeners.get(event) ?? []) listener(payload);
    },
    dispose() {
      for (const cleanup of cleanups.reverse()) cleanup();
    },
  };
}

test("registers the packaged skill in the host and existing Agent scopes", () => {
  const agentRegistrations = [];
  const agent = createAgent(agentRegistrations);
  const harness = createHarness([agent]);

  const result = apply(harness.context);

  assert.equal(name, "delivery-video");
  assert.deepEqual(inject, ["skills", "agents"]);
  assert.equal(result, undefined);
  assert.equal(harness.hostRegistrations.length, 1);
  assert.equal(agentRegistrations.length, 1);
  assert.equal(agentRegistrations[0].skill, harness.hostRegistrations[0]);

  const registered = harness.hostRegistrations[0];
  assert.equal(registered.name, "delivery-video");
  assert.match(registered.description, /delivery\/acceptance demo videos/);
  assert.match(registered.content, /^# Delivery Video/m);
  assert.equal(registered.content.includes("\nname: delivery-video\n"), false);
  assert.equal(registered.resourceBase.kind, "directory");
  assert.match(registered.resourceBase.path, /skills\/delivery-video\/$/);
  assert.deepEqual(registered.invocation, {
    modelInvocable: true,
    userInvocable: true,
  });
});

test("mirrors the skill into new Agents and releases every registration", () => {
  const currentRegistrations = [];
  const futureRegistrations = [];
  const current = createAgent(currentRegistrations);
  const future = createAgent(futureRegistrations);
  const harness = createHarness([current]);

  apply(harness.context);
  harness.emit("agent/created", { agent: future });

  assert.equal(currentRegistrations.length, 1);
  assert.equal(futureRegistrations.length, 1);
  assert.equal(futureRegistrations[0].disposed, 0);

  harness.emit("agent/disposed", { agent: future });
  assert.equal(futureRegistrations[0].disposed, 1);
  assert.equal(currentRegistrations[0].disposed, 0);

  harness.dispose();
  assert.equal(currentRegistrations[0].disposed, 1);
});
