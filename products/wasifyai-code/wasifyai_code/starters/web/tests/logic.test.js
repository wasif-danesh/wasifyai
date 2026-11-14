import assert from "node:assert/strict";
import { test } from "node:test";
import { greeting } from "../src/logic.js";

test("says good morning before noon", () => {
  assert.equal(greeting(new Date(2026, 0, 5, 9, 0)), "Good morning.");
});

test("says good afternoon until six", () => {
  assert.equal(greeting(new Date(2026, 0, 5, 15, 0)), "Good afternoon.");
});

test("says good evening after six", () => {
  assert.equal(greeting(new Date(2026, 0, 5, 20, 0)), "Good evening.");
});
