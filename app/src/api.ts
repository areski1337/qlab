// Client de l'API locale : passe exclusivement par le pont IPC du preload.
type Resp = { status: number; data: any };
declare global {
  interface Window {
    qlab: {
      request: (m: "GET" | "POST" | "PUT", p: string, b?: unknown) => Promise<Resp>;
      onEvent: (cb: (ev: any) => void) => () => void;
      revealExport: (p: string) => Promise<boolean>;
      engineLog: () => Promise<string>;
      update: (op: "status" | "check" | "set-source" | "download" | "install", arg?: string) => Promise<any>;
    };
  }
}

export class ApiError extends Error {
  constructor(public status: number, public data: any) {
    super(typeof data?.detail === "string" ? data.detail : JSON.stringify(data?.detail ?? data));
  }
}

async function call(m: "GET" | "POST" | "PUT", p: string, b?: unknown) {
  const r = await window.qlab.request(m, `/api/v1${p}`, b);
  if (r.status >= 400) throw new ApiError(r.status, r.data);
  return r.data;
}

export const api = {
  get: (p: string) => call("GET", p),
  post: (p: string, b: unknown = {}) => call("POST", p, b),
  put: (p: string, b: unknown) => call("PUT", p, b),
};
