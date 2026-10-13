"use strict";
var __createBinding = (this && this.__createBinding) || (Object.create ? (function(o, m, k, k2) {
    if (k2 === undefined) k2 = k;
    var desc = Object.getOwnPropertyDescriptor(m, k);
    if (!desc || ("get" in desc ? !m.__esModule : desc.writable || desc.configurable)) {
      desc = { enumerable: true, get: function() { return m[k]; } };
    }
    Object.defineProperty(o, k2, desc);
}) : (function(o, m, k, k2) {
    if (k2 === undefined) k2 = k;
    o[k2] = m[k];
}));
var __setModuleDefault = (this && this.__setModuleDefault) || (Object.create ? (function(o, v) {
    Object.defineProperty(o, "default", { enumerable: true, value: v });
}) : function(o, v) {
    o["default"] = v;
});
var __importStar = (this && this.__importStar) || (function () {
    var ownKeys = function(o) {
        ownKeys = Object.getOwnPropertyNames || function (o) {
            var ar = [];
            for (var k in o) if (Object.prototype.hasOwnProperty.call(o, k)) ar[ar.length] = k;
            return ar;
        };
        return ownKeys(o);
    };
    return function (mod) {
        if (mod && mod.__esModule) return mod;
        var result = {};
        if (mod != null) for (var k = ownKeys(mod), i = 0; i < k.length; i++) if (k[i] !== "default") __createBinding(result, mod, k[i]);
        __setModuleDefault(result, mod);
        return result;
    };
})();
Object.defineProperty(exports, "__esModule", { value: true });
// Processus principal Electron : lance le moteur Python local, relaie l'API via IPC validé.
// Le renderer n'a ni Node ni accès réseau direct : il ne peut appeler que les chemins /api/v1 autorisés.
const electron_1 = require("electron");
const node_url_1 = require("node:url");
const node_child_process_1 = require("node:child_process");
const node_crypto_1 = require("node:crypto");
const path = __importStar(require("node:path"));
const fs = __importStar(require("node:fs"));
const TOKEN = (0, node_crypto_1.randomBytes)(32).toString("hex");
let port = 0;
let engine = null;
let engineLog = [];
let win = null;
let sseAbort = null;
// Protocole app:// : sert uniquement les fichiers du renderer empaqueté (origine stable pour la CSP 'self').
electron_1.protocol.registerSchemesAsPrivileged([{ scheme: "app", privileges: { standard: true, secure: true, supportFetchAPI: false } }]);
const RENDERER_DIR = path.join(__dirname, "..", "dist", "renderer");
const PATH_RE = /^\/api\/v1\/[A-Za-z0-9_\-./]*(\?[A-Za-z0-9_\-.=&%]*)?$/;
const METHODS = new Set(["GET", "POST", "PUT"]);
function engineDir() {
    // Développement : ../engine ; application empaquetée : resources/engine (voir docs/operations/installation.md)
    const packaged = path.join(process.resourcesPath, "engine");
    return fs.existsSync(packaged) ? packaged : path.resolve(__dirname, "..", "..", "engine");
}
function startEngine() {
    return new Promise((resolve, reject) => {
        const dir = engineDir();
        const args = ["run", "--project", dir, "python", "-m", "qlab.api.app"];
        if (process.env.QLAB_DATA_DIR)
            args.push("--data-dir", process.env.QLAB_DATA_DIR);
        engine = (0, node_child_process_1.spawn)("uv", args, { cwd: dir, env: { ...process.env, QLAB_API_TOKEN: TOKEN }, windowsHide: true });
        const timer = setTimeout(() => reject(new Error("le moteur n'a pas démarré en 120 s")), 120_000);
        engine.stdout?.on("data", (d) => {
            const s = d.toString();
            engineLog.push(s);
            const m = /QLAB_API_READY port=(\d+)/.exec(s);
            if (m) {
                port = Number(m[1]);
                clearTimeout(timer);
                resolve();
            }
        });
        engine.stderr?.on("data", (d) => { engineLog.push(d.toString()); engineLog = engineLog.slice(-200); });
        engine.on("exit", (code) => {
            clearTimeout(timer);
            win?.webContents.send("qlab:event", { type: "engine.exited", code, ts: new Date().toISOString() });
            if (!port)
                reject(new Error(`moteur arrêté (code ${code}) : ${engineLog.join("").slice(-2000)}`));
        });
    });
}
async function apiRequest(method, p, body) {
    if (!METHODS.has(method))
        throw new Error("méthode refusée");
    if (!PATH_RE.test(p) || p.includes(".."))
        throw new Error("chemin refusé");
    if (!port)
        return { status: 503, data: { error: "moteur indisponible", log: engineLog.join("").slice(-2000) } };
    const r = await fetch(`http://127.0.0.1:${port}${p}`, {
        method,
        headers: { "X-QLab-Token": TOKEN, "Content-Type": "application/json" },
        body: body === undefined ? undefined : JSON.stringify(body),
    });
    const ct = r.headers.get("content-type") || "";
    const data = ct.includes("json") ? await r.json() : await r.text();
    return { status: r.status, data };
}
async function pumpEvents() {
    sseAbort = new AbortController();
    for (;;) {
        try {
            const r = await fetch(`http://127.0.0.1:${port}/api/v1/events`, {
                headers: { "X-QLab-Token": TOKEN }, signal: sseAbort.signal,
            });
            const reader = r.body.getReader();
            const dec = new TextDecoder();
            let buf = "";
            for (;;) {
                const { value, done } = await reader.read();
                if (done)
                    break;
                buf += dec.decode(value, { stream: true });
                let i;
                while ((i = buf.indexOf("\n\n")) >= 0) {
                    const chunk = buf.slice(0, i);
                    buf = buf.slice(i + 2);
                    const line = chunk.split("\n").find((l) => l.startsWith("data: "));
                    if (line)
                        win?.webContents.send("qlab:event", JSON.parse(line.slice(6)));
                }
            }
        }
        catch {
            if (sseAbort.signal.aborted)
                return;
        }
        await new Promise((res) => setTimeout(res, 2000));
    }
}
const SNAP_DIR = process.env.QLAB_UI_SNAPSHOT_DIR;
// Mode QA : capture chaque écran dans une fenêtre cachée (aucune interaction avec le bureau), puis quitte.
async function snapshots(dir) {
    fs.mkdirSync(dir, { recursive: true });
    const n = await win.webContents.executeJavaScript("document.querySelectorAll('nav button').length");
    for (let i = 0; i < n; i++) {
        await win.webContents.executeJavaScript(`document.querySelectorAll('nav button')[${i}].click()`);
        await new Promise((r) => setTimeout(r, 2500));
        const img = await win.webContents.capturePage();
        fs.writeFileSync(path.join(dir, `screen-${String(i + 1).padStart(2, "0")}.png`), img.toPNG());
    }
    fs.writeFileSync(path.join(dir, "renderer-log.txt"), engineLog.filter((l) => l.startsWith("[renderer")).join(""));
    electron_1.app.quit();
}
function createWindow() {
    win = new electron_1.BrowserWindow({
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
        if (e.level === "error" || e.level === "warning")
            engineLog.push(`[renderer ${e.level}] ${e.message}
`);
    });
    win.loadURL("app://bundle/index.html");
}
electron_1.app.whenReady().then(async () => {
    electron_1.Menu.setApplicationMenu(null);
    electron_1.protocol.handle("app", (req) => {
        const rel = decodeURIComponent(new URL(req.url).pathname).replace(/^\/+/, "");
        const target = path.resolve(RENDERER_DIR, rel || "index.html");
        if (!target.startsWith(RENDERER_DIR + path.sep))
            return new Response("refusé", { status: 403 });
        return electron_1.net.fetch((0, node_url_1.pathToFileURL)(target).toString());
    });
    electron_1.session.defaultSession.setPermissionRequestHandler((_wc, _perm, cb) => cb(false));
    electron_1.ipcMain.handle("qlab:request", async (e, method, p, body) => {
        if (!e.senderFrame?.url.startsWith("app://bundle/"))
            throw new Error("origine refusée");
        if (typeof method !== "string" || typeof p !== "string")
            throw new Error("arguments invalides");
        return apiRequest(method, p, body);
    });
    electron_1.ipcMain.handle("qlab:reveal-export", async (_e, p) => {
        // n'ouvre que des fichiers du répertoire d'exports du moteur (chemin validé côté moteur)
        const h = await apiRequest("GET", "/api/v1/health");
        const root = h.data.data_dir;
        if (typeof p !== "string" || !root)
            return false;
        const target = path.resolve(p);
        if (!target.startsWith(path.resolve(root, "exports") + path.sep))
            return false;
        electron_1.shell.showItemInFolder(target);
        return true;
    });
    electron_1.ipcMain.handle("qlab:engine-log", async () => engineLog.join("").slice(-4000));
    createWindow();
    try {
        await startEngine();
        win?.webContents.send("qlab:event", { type: "engine.ready", ts: new Date().toISOString() });
        pumpEvents();
        if (SNAP_DIR)
            setTimeout(() => snapshots(SNAP_DIR), 3000);
    }
    catch (err) {
        win?.webContents.send("qlab:event", { type: "engine.failed", error: String(err), ts: new Date().toISOString() });
    }
});
electron_1.app.on("window-all-closed", () => {
    sseAbort?.abort();
    engine?.kill();
    electron_1.app.quit();
});
