// API minimale exposée au renderer (contextIsolation) : aucun accès Node, aucun chemin arbitraire.
import { contextBridge, ipcRenderer } from "electron";

contextBridge.exposeInMainWorld("qlab", {
  request: (method: "GET" | "POST" | "PUT", path: string, body?: unknown) =>
    ipcRenderer.invoke("qlab:request", method, path, body),
  onEvent: (cb: (ev: unknown) => void) => {
    const h = (_: unknown, ev: unknown) => cb(ev);
    ipcRenderer.on("qlab:event", h);
    return () => ipcRenderer.removeListener("qlab:event", h);
  },
  revealExport: (p: string) => ipcRenderer.invoke("qlab:reveal-export", p),
  engineLog: () => ipcRenderer.invoke("qlab:engine-log"),
});
