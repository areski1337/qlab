"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
// API minimale exposée au renderer (contextIsolation) : aucun accès Node, aucun chemin arbitraire.
const electron_1 = require("electron");
electron_1.contextBridge.exposeInMainWorld("qlab", {
    request: (method, path, body) => electron_1.ipcRenderer.invoke("qlab:request", method, path, body),
    onEvent: (cb) => {
        const h = (_, ev) => cb(ev);
        electron_1.ipcRenderer.on("qlab:event", h);
        return () => electron_1.ipcRenderer.removeListener("qlab:event", h);
    },
    revealExport: (p) => electron_1.ipcRenderer.invoke("qlab:reveal-export", p),
    engineLog: () => electron_1.ipcRenderer.invoke("qlab:engine-log"),
});
