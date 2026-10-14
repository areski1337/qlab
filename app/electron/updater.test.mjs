// Auto-contrôle hors Electron : node --test dist-electron (après npm run build:main)
import { test } from "node:test";
import assert from "node:assert/strict";
import { generateKeyPairSync, sign } from "node:crypto";
import { newer, validManifest, signatureValid, signaturePayload } from "../dist-electron/updater.js";
import { payload } from "../../scripts/sign_manifest.mjs";

test("comparaison de versions", () => {
  assert.ok(newer("0.2.0", "0.1.0"));
  assert.ok(newer("0.10.0", "0.9.9"));
  assert.ok(!newer("0.1.0", "0.1.0"));
  assert.ok(!newer("0.1.0", "0.2.0"));
  assert.ok(!newer("0.2.0-beta", "0.2.0"));
});

test("manifeste : rejette noms de fichier et empreintes suspects", () => {
  const ok = { version: "0.2.0", file: "QLab Setup 0.2.0.exe", sha512: "a".repeat(128), size: 10, signature: "A".repeat(86) + "==" };
  assert.ok(validManifest(ok));
  assert.ok(!validManifest({ ...ok, file: "..\\evil.exe" }));
  assert.ok(!validManifest({ ...ok, file: "x.bat" }));
  assert.ok(!validManifest({ ...ok, sha512: "abc" }));
  assert.ok(!validManifest({ ...ok, size: 0 }));
  assert.ok(!validManifest({ ...ok, version: "latest" }));
});

test("manifeste : signature Ed25519 exigée et vérifiée", () => {
  const { privateKey, publicKey } = generateKeyPairSync("ed25519");
  const pem = publicKey.export({ type: "spki", format: "pem" }).toString();
  const m = { version: "0.6.0", file: "QLab.Setup.0.6.0.exe", sha512: "b".repeat(128), size: 42 };
  assert.equal(signaturePayload(m), payload(m));  // même charge signée côté publication et côté application
  const signed = { ...m, signature: sign(null, Buffer.from(payload(m)), privateKey).toString("base64") };
  assert.ok(validManifest(signed) && signatureValid(signed, pem));
  assert.ok(!validManifest(m));                                         // non signé
  assert.ok(!signatureValid({ ...signed, sha512: "c".repeat(128) }, pem));  // installateur substitué
  assert.ok(!signatureValid({ ...signed, version: "9.9.9" }, pem));         // version falsifiée
  assert.ok(!signatureValid(signed));                                   // autre clé que la clé figée
});
