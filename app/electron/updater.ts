// Mises à jour de l'application : lit un manifeste `latest.json` publié par scripts/build_installer.ps1
// dans une source : par défaut les releases GitHub du dépôt QLab (github:propriétaire/dépôt), sinon un dossier
// local / partage réseau ou une URL https choisis par l'utilisateur. Télécharge
// l'installateur, vérifie son empreinte SHA-512 et ne l'exécute qu'à la demande explicite de l'utilisateur.
// Les données (base, artefacts, datasets) vivent hors du dossier d'installation : la mise à jour ne les touche
// pas ; les migrations de base s'appliquent au redémarrage du moteur, avec sauvegarde préalable.
import { app } from "electron";
import { createHash } from "node:crypto";
import { spawn, spawnSync } from "node:child_process";
import * as fs from "node:fs";
import * as path from "node:path";

export type Manifest = { version: string; file: string; sha512: string; size: number; released_at?: string; notes?: string };
export type UpdateState = {
  current: string; source: string | null; checked_at: string | null; available: Manifest | null;
  downloaded: string | null; progress: number | null; error: string | null;
};

const CFG = () => path.join(app.getPath("userData"), "update.json");
const DIR = () => path.join(app.getPath("userData"), "updates");
const FILE_RE = /^[A-Za-z0-9 ._-]+\.exe$/;
const GH_RE = /^github:([A-Za-z0-9-]+)\/([A-Za-z0-9._-]+)$/;
export const DEFAULT_SOURCE = "github:areski1337/qlab";  // releases publiées par scripts/build_installer.ps1 -Release

const state: UpdateState = { current: "", source: null, checked_at: null, available: null,
  downloaded: null, progress: null, error: null };

export function getSource(): string | null {
  if (process.env.QLAB_UPDATE_SOURCE) return process.env.QLAB_UPDATE_SOURCE;
  try { return JSON.parse(fs.readFileSync(CFG(), "utf-8")).source || DEFAULT_SOURCE; } catch { return DEFAULT_SOURCE; }
}

function isUrl(s: string) { return /^https?:\/\//i.test(s); }

export function setSource(src: string): UpdateState {
  const s = src.trim();
  if (s && isUrl(s) && !/^https:\/\//i.test(s)) throw new Error("source refusée : http non chiffré (utiliser https ou un dossier)");
  if (s && !isUrl(s) && !GH_RE.test(s) && !path.isAbsolute(s)) throw new Error("source refusée : github:propriétaire/dépôt, chemin de dossier absolu ou URL https attendu");
  fs.mkdirSync(path.dirname(CFG()), { recursive: true });
  fs.writeFileSync(CFG(), JSON.stringify({ source: s || null }, null, 2));
  Object.assign(state, { source: s || null, available: null, downloaded: null, error: null });
  return status();
}

export function status(): UpdateState { return { ...state, current: app.getVersion(), source: getSource() }; }

// Comparaison x.y.z (suffixes de pré-version ignorés : une pré-version n'est jamais proposée au-dessus de sa finale).
export function newer(a: string, b: string): boolean {
  const p = (v: string) => v.split("-")[0].split(".").map((x) => Number(x) || 0);
  const [x, y] = [p(a), p(b)];
  for (let i = 0; i < 3; i++) if ((x[i] ?? 0) !== (y[i] ?? 0)) return (x[i] ?? 0) > (y[i] ?? 0);
  return false;
}

function join(src: string, name: string) {
  return isUrl(src) ? new URL(encodeURIComponent(name), src.endsWith("/") ? src : src + "/").toString() : path.join(src, name);
}

// Jeton GitHub (dépôt privé) : variable d'environnement, sinon session GitHub CLI du poste. Jamais stocké ni journalisé,
// envoyé uniquement à api.github.com (fetch retire l'en-tête Authorization lors de la redirection vers le stockage signé).
let ghToken: string | null | undefined;
function token(): string | null {
  if (ghToken !== undefined) return ghToken;
  ghToken = process.env.GH_TOKEN || process.env.GITHUB_TOKEN || null;
  for (const exe of ghToken ? [] : ["gh", "C:\\Program Files\\GitHub CLI\\gh.exe"]) {
    const r = spawnSync(exe, ["auth", "token"], { encoding: "utf-8", windowsHide: true, timeout: 10_000 });
    if (r.status === 0 && r.stdout.trim()) { ghToken = r.stdout.trim(); break; }
  }
  return ghToken;
}

async function ghAsset(src: string, name: string): Promise<Response> {
  const [, owner, repo] = GH_RE.exec(src)!;
  const t = token();
  const h: Record<string, string> = { "X-GitHub-Api-Version": "2022-11-28", ...(t ? { Authorization: `Bearer ${t}` } : {}) };
  const rel = await fetch(`https://api.github.com/repos/${owner}/${repo}/releases/latest`, { headers: { ...h, Accept: "application/vnd.github+json" }, cache: "no-store" });
  if (rel.status === 404) throw new Error(t ? "aucune release publiée sur le dépôt" : "dépôt privé inaccessible : connecter GitHub CLI sur ce poste (gh auth login)");
  if (!rel.ok) throw new Error(`GitHub : HTTP ${rel.status}`);
  const a = ((await rel.json()).assets ?? []).find((x: any) => x.name === name);
  if (!a) throw new Error(`fichier ${name} absent de la dernière release`);
  return fetch(a.url, { headers: { ...h, Accept: "application/octet-stream" }, cache: "no-store" });
}

async function remote(src: string, name: string): Promise<Response> {
  return GH_RE.test(src) ? ghAsset(src, name) : fetch(join(src, name), { cache: "no-store" });
}

async function readText(src: string, name: string): Promise<string> {
  if (!isUrl(src) && !GH_RE.test(src)) return fs.readFileSync(join(src, name), "utf-8");
  const r = await remote(src, name);
  if (!r.ok) throw new Error(`manifeste inaccessible (HTTP ${r.status})`);
  return r.text();
}

export function validManifest(m: any): m is Manifest {
  return m && typeof m.version === "string" && /^\d+\.\d+\.\d+([-.][0-9A-Za-z.-]+)?$/.test(m.version)
    && typeof m.file === "string" && FILE_RE.test(m.file) && typeof m.sha512 === "string"
    && /^[0-9a-f]{128}$/.test(m.sha512) && Number.isInteger(m.size) && m.size > 0;
}

export async function check(): Promise<UpdateState> {
  const src = getSource();
  state.checked_at = new Date().toISOString();
  state.error = null;
  if (!src) { state.available = null; return status(); }
  try {
    const m = JSON.parse((await readText(src, "latest.json")).replace(/^﻿/, ""));
    if (!validManifest(m)) throw new Error("manifeste latest.json invalide");
    state.available = newer(m.version, app.getVersion()) ? m : null;
    if (state.downloaded && state.available?.file !== path.basename(state.downloaded)) state.downloaded = null;
  } catch (e) {
    state.available = null;
    state.error = `vérification impossible : ${(e as Error).message}`;
  }
  return status();
}

export async function download(onProgress: (s: UpdateState) => void): Promise<UpdateState> {
  const m = state.available, src = getSource();
  if (!m || !src) throw new Error("aucune mise à jour disponible");
  fs.mkdirSync(DIR(), { recursive: true });
  for (const f of fs.readdirSync(DIR())) fs.rmSync(path.join(DIR(), f), { force: true });  // anciennes versions
  const dest = path.join(DIR(), m.file), tmp = dest + ".part";
  const h = createHash("sha512");
  let got = 0;
  state.error = null; state.downloaded = null; state.progress = 0;
  const out = fs.createWriteStream(tmp);
  const write = (chunk: Buffer | Uint8Array) => new Promise<void>((res, rej) => {
    h.update(chunk); got += chunk.length;
    if (got > m.size) return rej(new Error("taille supérieure à celle du manifeste"));
    const p = Math.floor((got / m.size) * 100);
    if (p !== state.progress) { state.progress = p; onProgress(status()); }
    out.write(chunk, (e) => (e ? rej(e) : res()));
  });
  try {
    if (isUrl(src) || GH_RE.test(src)) {
      const r = await remote(src, m.file);
      if (!r.ok || !r.body) throw new Error(`téléchargement refusé (HTTP ${r.status})`);
      const reader = r.body.getReader();
      for (;;) { const { value, done } = await reader.read(); if (done) break; await write(value); }
    } else {
      for await (const chunk of fs.createReadStream(join(src, m.file), { highWaterMark: 1 << 20 })) await write(chunk as Buffer);
    }
    await new Promise<void>((res, rej) => out.end((e?: Error | null) => (e ? rej(e) : res())));
    if (got !== m.size) throw new Error(`taille ${got} ≠ ${m.size} octets annoncés`);
    if (h.digest("hex") !== m.sha512) throw new Error("empreinte SHA-512 différente du manifeste : fichier rejeté");
    fs.renameSync(tmp, dest);
    state.downloaded = dest;
  } catch (e) {
    out.destroy();
    fs.rmSync(tmp, { force: true });
    state.error = (e as Error).message;
  } finally {
    state.progress = null;
  }
  return status();
}

// Lance l'installateur NSIS en mode silencieux (même dossier d'installation, --force-run relance QLab),
// puis l'appelant quitte l'application (le moteur est arrêté par will-quit).
export function install(): void {
  const f = state.downloaded;
  if (!f || !fs.existsSync(f)) throw new Error("aucun installateur vérifié");
  if (!app.isPackaged) throw new Error("installation désactivée en développement (application non empaquetée)");
  spawn(f, ["/S", "--updated", "--force-run"], { detached: true, stdio: "ignore", windowsHide: true }).unref();
}
