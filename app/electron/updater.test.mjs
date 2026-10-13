// Auto-contrôle hors Electron : node --test dist-electron (après npm run build:main)
import { test } from "node:test";
import assert from "node:assert/strict";
import { newer, validManifest } from "../dist-electron/updater.js";

test("comparaison de versions", () => {
  assert.ok(newer("0.2.0", "0.1.0"));
  assert.ok(newer("0.10.0", "0.9.9"));
  assert.ok(!newer("0.1.0", "0.1.0"));
  assert.ok(!newer("0.1.0", "0.2.0"));
  assert.ok(!newer("0.2.0-beta", "0.2.0"));
});

test("manifeste : rejette noms de fichier et empreintes suspects", () => {
  const ok = { version: "0.2.0", file: "QLab Setup 0.2.0.exe", sha512: "a".repeat(128), size: 10 };
  assert.ok(validManifest(ok));
  assert.ok(!validManifest({ ...ok, file: "..\\evil.exe" }));
  assert.ok(!validManifest({ ...ok, file: "x.bat" }));
  assert.ok(!validManifest({ ...ok, sha512: "abc" }));
  assert.ok(!validManifest({ ...ok, size: 0 }));
  assert.ok(!validManifest({ ...ok, version: "latest" }));
});
