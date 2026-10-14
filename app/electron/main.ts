// Processus principal Electron : lance le moteur Python local, relaie l'API via IPC validé.
// Le renderer n'a ni Node ni accès réseau direct : il ne peut appeler que les chemins /api/v1 autorisés.
import { app, BrowserWindow, ipcMain, Menu, net, Notification, protocol, shell, session } from "electron";
import { pathToFileURL } from "node:url";
import { spawn, spawnSync, ChildProcess } from "node:child_process";
import { randomBytes } from "node:crypto";
import * as path from "node:path";
import * as fs from "node:fs";
import * as updater from "./updater";

const TOKEN = randomBytes(32).toString("hex");
let port = 0;
let engine: ChildProcess | null = null;
let engineLog: string[] = [];
let win: BrowserWindow | null = null;
let sseAbort: AbortController | null = null;

// Envoi au renderer sans planter si la fenêtre est déjà détruite (fermeture : le moteur s'arrête après elle).
function sendToWin(channel: string, payload: unknown) {
  if (win && !win.isDestroyed() && !win.webContents.isDestroyed()) win.webContents.send(channel, payload);
}

// Protocole app:// : sert uniquement les fichiers du renderer empaqueté (origine stable pour la CSP 'self').
protocol.registerSchemesAsPrivileged([{ scheme: "app", privileges: { standard: true, secure: true, supportFetchAPI: false } }]);
const RENDERER_DIR = path.join(__dirname, "..", "dist", "renderer");

const PATH_RE = /^\/api\/v1\/[A-Za-z0-9_\-./]*(\?[A-Za-z0-9_\-.=&%]*)?$/;
const METHODS = new Set(["GET", "POST", "PUT"]);

function engineDir(): string {
  // Développement : ../engine ; application empaquetée : resources/engine (voir docs/operations/installation.md)
  const packaged = path.join(process.resourcesPath, "engine");
  return fs.existsSync(packaged) ? packaged : path.resolve(__dirname, "..", "..", "engine");
}

function startEngine(): Promise<void> {
  return new Promise((resolve, reject) => {
    const dir = engineDir();
    const env: NodeJS.ProcessEnv = { ...process.env, QLAB_API_TOKEN: TOKEN };
    const extra = process.env.QLAB_DATA_DIR ? ["--data-dir", process.env.QLAB_DATA_DIR] : [];
    // Installateur autonome : Python embarqué (resources/python) + sources du moteur, sans uv.
    const bundled = path.join(process.resourcesPath, "python", "python.exe");
    if (app.isPackaged && fs.existsSync(bundled)) {
      env.PYTHONPATH = path.join(dir, "src");
      env.PYTHONDONTWRITEBYTECODE = "1";  // dossier d'installation potentiellement en lecture seule
      engine = spawn(bundled, ["-m", "qlab.api.app", ...extra], { cwd: app.getPath("userData"), env, windowsHide: true });
    } else {
      // Développement (ou paquet sans Python embarqué) : uv gère l'environnement, dans le profil si empaqueté.
      if (app.isPackaged) env.UV_PROJECT_ENVIRONMENT = path.join(app.getPath("userData"), "engine-venv");
      engine = spawn("uv", ["run", "--project", dir, "python", "-m", "qlab.api.app", ...extra], { cwd: dir, env, windowsHide: true });
    }
    const timer = setTimeout(() => reject(new Error("le moteur n'a pas démarré en 120 s")), 120_000);
    engine.stdout?.on("data", (d: Buffer) => {
      const s = d.toString();
      engineLog.push(s);
      const m = /QLAB_API_READY port=(\d+)/.exec(s);
      if (m) { port = Number(m[1]); clearTimeout(timer); resolve(); }
    });
    engine.stderr?.on("data", (d: Buffer) => { engineLog.push(d.toString()); engineLog = engineLog.slice(-200); });
    engine.on("exit", (code) => {
      clearTimeout(timer);
      sendToWin("qlab:event", { type: "engine.exited", code, ts: new Date().toISOString() });
      if (!port) reject(new Error(`moteur arrêté (code ${code}) : ${engineLog.join("").slice(-2000)}`));
    });
  });
}

async function apiRequest(method: string, p: string, body?: unknown) {
  if (!METHODS.has(method)) throw new Error("méthode refusée");
  if (!PATH_RE.test(p) || p.includes("..")) throw new Error("chemin refusé");
  if (!port) return { status: 503, data: { error: "moteur indisponible", log: engineLog.join("").slice(-2000) } };
  const r = await fetch(`http://127.0.0.1:${port}${p}`, {
    method,
    headers: { "X-QLab-Token": TOKEN, "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const ct = r.headers.get("content-type") || "";
  const data = ct.includes("json") ? await r.json() : await r.text();
  return { status: r.status, data };
}

// Notification Windows quand une tâche se termine ou échoue (seulement celles mises à jour après le lancement :
// le flux d'événements rejoue l'historique à la connexion).
const STARTED = new Date().toISOString();
const KIND_FR: Record<string, string> = { campaign: "Campagne", advance: "Validation", final_test: "Test final", mt5_verify: "Vérification MT5",
  import_mt5: "Import MT5", backtest: "Backtest", export: "Export", calendar_refresh: "Calendrier", backup: "Sauvegarde",
  demo_observe: "Observation démo", engine_experiment: "Expérience moteur" };
function notify(ev: any) {
  const t = ev?.task;
  if (ev?.type !== "task.updated" || !t || !Notification.isSupported() || (t.updated_at ?? "") < STARTED) return;
  if (!["completed", "failed", "quarantined"].includes(t.state)) return;
  const n = new Notification({ title: `QLab — ${KIND_FR[t.kind] ?? t.kind} : ${t.state === "completed" ? "terminé" : "échec"}`,
    body: t.state === "completed" ? "Résultats disponibles dans QLab." : String(t.error ?? "voir Tâches & journaux").slice(0, 180) });
  n.on("click", () => { win?.show(); win?.focus(); });
  n.show();
}

async function pumpEvents() {
  sseAbort = new AbortController();
  for (;;) {
    try {
      const r = await fetch(`http://127.0.0.1:${port}/api/v1/events`, {
        headers: { "X-QLab-Token": TOKEN }, signal: sseAbort.signal,
      });
      const reader = r.body!.getReader();
      const dec = new TextDecoder();
      let buf = "";
      for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        buf += dec.decode(value, { stream: true });
        let i;
        while ((i = buf.indexOf("\n\n")) >= 0) {
          const chunk = buf.slice(0, i);
          buf = buf.slice(i + 2);
          const line = chunk.split("\n").find((l) => l.startsWith("data: "));
          if (line) { const ev = JSON.parse(line.slice(6)); notify(ev); sendToWin("qlab:event", ev); }
        }
      }
    } catch {
      if (sseAbort.signal.aborted) return;
    }
    await new Promise((res) => setTimeout(res, 2000));
  }
}

const SNAP_DIR = process.env.QLAB_UI_SNAPSHOT_DIR;

// Mode QA : capture chaque écran dans une fenêtre cachée (aucune interaction avec le bureau), puis quitte.
async function snapshots(dir: string) {
  fs.mkdirSync(dir, { recursive: true });
  const theme = process.env.QLAB_UI_SNAPSHOT_THEME;  // QA : capturer dans un thème donné (nocturne, graphite, ivoire, ambre)
  if (theme && /^[a-z]+$/.test(theme)) {
    await win!.webContents.executeJavaScript(`(() => { const k = "qlab.prefs.v1"; const p = JSON.parse(localStorage.getItem(k) || "{}"); p.theme = "${theme}"; localStorage.setItem(k, JSON.stringify(p)); })()`);
    win!.webContents.reload();
    await new Promise((r) => setTimeout(r, 3000));
  }
  const n = await win!.webContents.executeJavaScript("document.querySelectorAll('nav button').length");
  for (let i = 0; i < n; i++) {
    await win!.webContents.executeJavaScript(`document.querySelectorAll('nav button')[${i}].click()`);
    await new Promise((r) => setTimeout(r, 2500));
    const img = await win!.webContents.capturePage();
    fs.writeFileSync(path.join(dir, `screen-${String(i + 1).padStart(2, "0")}.png`), img.toPNG());
    // vue détaillée : première ligne cliquable de l'écran (dataset, révision, évaluation…)
    if (await win!.webContents.executeJavaScript("(() => { const r = document.querySelector('main tbody tr.click'); if (r) r.click(); return !!r; })()")) {
      await new Promise((r) => setTimeout(r, 3500));
      // vue détaillée, page par page (défilement de <main>) : graphiques sous la ligne de flottaison inclus
      for (let k = 0; k < 4; k++) {
        const img2 = await win!.webContents.capturePage();
        fs.writeFileSync(path.join(dir, `screen-${String(i + 1).padStart(2, "0")}-b${k}.png`), img2.toPNG());
        const more = await win!.webContents.executeJavaScript("(() => { const m = document.querySelector('main'); const t = m.scrollTop; m.scrollTop += m.clientHeight - 40; return m.scrollTop > t; })()");
        if (!more) break;
        await new Promise((r) => setTimeout(r, 800));
      }
    }
  }
  fs.writeFileSync(path.join(dir, "renderer-log.txt"), engineLog.filter((l) => l.startsWith("[renderer")).join(""));
  app.quit();
}

function createWindow() {
  win = new BrowserWindow({
    show: !SNAP_DIR,
    width: 1440, height: 900, minWidth: 1024, minHeight: 680, title: "QLab — recherche quantitative",
    backgroundColor: "#111418",
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true, nodeIntegration: false, sandbox: true, webSecurity: true,
      allowRunningInsecureContent: false, spellcheck: false,
    },
  });
  win.webContents.setWindowOpenHandler(() => ({ action: "deny" }));
  win.webContents.on("will-navigate", (e) => e.preventDefault());
  win.webContents.on("console-message", (e) => {
    if (e.level === "error" || e.level === "warning") engineLog.push(`[renderer ${e.level}] ${e.message}
`);
  });
  win.loadURL("app://bundle/index.html");
}

app.setAppUserModelId("local.qlab.desktop");  // requis par Windows pour afficher les notifications
app.whenReady().then(async () => {
  Menu.setApplicationMenu(null);
  protocol.handle("app", (req) => {
    const rel = decodeURIComponent(new URL(req.url).pathname).replace(/^\/+/, "");
    const target = path.resolve(RENDERER_DIR, rel || "index.html");
    if (!target.startsWith(RENDERER_DIR + path.sep)) return new Response("refusé", { status: 403 });
    return net.fetch(pathToFileURL(target).toString());
  });
  session.defaultSession.setPermissionRequestHandler((_wc, _perm, cb) => cb(false));
  ipcMain.handle("qlab:request", async (e, method: unknown, p: unknown, body: unknown) => {
    if (!e.senderFrame?.url.startsWith("app://bundle/")) throw new Error("origine refusée");
    if (typeof method !== "string" || typeof p !== "string") throw new Error("arguments invalides");
    return apiRequest(method, p, body);
  });
  ipcMain.handle("qlab:reveal-export", async (_e, p: unknown) => {
    // n'ouvre que des fichiers du répertoire d'exports du moteur (chemin validé côté moteur)
    const h = await apiRequest("GET", "/api/v1/health");
    const root = (h.data as { data_dir?: string }).data_dir;
    if (typeof p !== "string" || !root) return false;
    const target = path.resolve(p);
    if (!target.startsWith(path.resolve(root, "exports") + path.sep)) return false;
    shell.showItemInFolder(target);
    return true;
  });
  ipcMain.handle("qlab:engine-log", async () => engineLog.join("").slice(-4000));
  // Mises à jour : même contrôle d'origine que l'API ; l'installation exige un fichier vérifié (SHA-512).
  ipcMain.handle("qlab:update", async (e, op: unknown, arg: unknown) => {
    if (!e.senderFrame?.url.startsWith("app://bundle/")) throw new Error("origine refusée");
    if (op === "status") return updater.status();
    if (op === "check") return updater.check();
    if (op === "set-source" && typeof arg === "string" && arg.length < 1024) return updater.setSource(arg);
    if (op === "download") return updater.download((s) => sendToWin("qlab:event", { type: "update.progress", ...s }));
    if (op === "install") {
      const t = await apiRequest("GET", "/api/v1/tasks");
      const busy = Array.isArray(t.data) ? t.data.filter((x: any) => x.state === "running" || x.state === "validating").length : 0;
      if (busy && arg !== "force") return { ...updater.status(), error: `${busy} tâche(s) en cours : elles seront mises en pause puis reprises au redémarrage. Confirmer pour installer quand même.`, busy };
      updater.install();
      setTimeout(() => app.quit(), 500);
      return updater.status();
    }
    throw new Error("opération refusée");
  });
  createWindow();
  try {
    await startEngine();
    sendToWin("qlab:event", { type: "engine.ready", ts: new Date().toISOString() });
    pumpEvents();
    // Vérification automatique au démarrage (source configurée uniquement) ; rien n'est téléchargé sans action.
    setTimeout(async () => {
      const s = await updater.check();
      if (s.available) sendToWin("qlab:event", { type: "update.available", version: s.available.version, ts: new Date().toISOString() });
    }, 15_000);
    if (SNAP_DIR) setTimeout(() => snapshots(SNAP_DIR), 3000);
  } catch (err) {
    sendToWin("qlab:event", { type: "engine.failed", error: String(err), ts: new Date().toISOString() });
  }
});

// Arrête tout l'arbre du moteur (uv → python → python) : tuer uv seul laisserait des processus orphelins.
function stopEngine() {
  sseAbort?.abort();
  if (engine?.pid && engine.exitCode === null) {
    spawnSync("taskkill", ["/PID", String(engine.pid), "/T", "/F"], { windowsHide: true });
  }
}
app.on("will-quit", stopEngine);
app.on("window-all-closed", () => {
  stopEngine();
  app.quit();
});
