// Signature Ed25519 du manifeste de mise à jour (latest.json), vérifiée par app/electron/updater.ts avec la clé
// publique figée dans l'application. La clé privée ne quitte jamais ce poste et n'est jamais dans le dépôt.
//   node scripts/sign_manifest.mjs <latest.json>      signe (clé : $QLAB_UPDATE_KEY ou ~/.qlab/update_ed25519.pem)
//   node scripts/sign_manifest.mjs --generate         crée la paire de clés et affiche la clé publique à figer
import { generateKeyPairSync, createPrivateKey, createPublicKey, sign, verify } from "node:crypto";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { pathToFileURL } from "node:url";

const KEY = process.env.QLAB_UPDATE_KEY || path.join(os.homedir(), ".qlab", "update_ed25519.pem");

// Doit rester identique à signaturePayload() dans app/electron/updater.ts.
export const payload = (m) => `qlab-update-v1\n${m.version}\n${m.file}\n${m.size}\n${m.sha512}`;

const main = process.argv[1] && import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href;
const arg = main ? process.argv[2] : undefined;
if (!main) {
  // importé (tests) : aucune action
} else if (arg === "--generate") {
  if (fs.existsSync(KEY)) throw new Error(`clé déjà présente : ${KEY} (ne jamais l'écraser : les mises à jour deviendraient impossibles)`);
  const { privateKey, publicKey } = generateKeyPairSync("ed25519");
  fs.mkdirSync(path.dirname(KEY), { recursive: true });
  fs.writeFileSync(KEY, privateKey.export({ type: "pkcs8", format: "pem" }), { mode: 0o600 });
  console.log(publicKey.export({ type: "spki", format: "pem" }));
} else if (arg) {
  if (!fs.existsSync(KEY)) throw new Error(`clé de signature introuvable : ${KEY}`);
  const key = createPrivateKey(fs.readFileSync(KEY));
  const m = JSON.parse(fs.readFileSync(arg, "utf-8").replace(/^﻿/, ""));
  m.signature = sign(null, Buffer.from(payload(m), "utf-8"), key).toString("base64");
  if (!verify(null, Buffer.from(payload(m), "utf-8"), createPublicKey(key), Buffer.from(m.signature, "base64")))
    throw new Error("auto-vérification de la signature échouée");
  fs.writeFileSync(arg, JSON.stringify(m, null, 2));
  console.log(`manifeste signé : ${arg}`);
} else {
  console.error("usage : node scripts/sign_manifest.mjs <latest.json> | --generate");
  process.exit(2);
}
