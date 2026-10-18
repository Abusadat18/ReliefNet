export type Credentials = { headers: Record<string, string>; query: Record<string, string> };
type CredentialSource = () => Promise<Credentials>;

let source: CredentialSource = async () => ({ headers: {}, query: {} });

export function setCredentialSource(fn: CredentialSource) {
  source = fn;
}

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

async function request<T>(method: string, path: string, body?: unknown, form?: FormData): Promise<T> {
  const cred = await source();
  const headers: Record<string, string> = { ...cred.headers };
  let payload: BodyInit | undefined;
  if (form) payload = form;
  else if (body !== undefined) {
    headers["content-type"] = "application/json";
    payload = JSON.stringify(body);
  }
  const res = await fetch(path, { method, headers, body: payload });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const j = await res.json();
      detail = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail);
    } catch {
      /* body was not JSON */
    }
    throw new ApiError(res.status, detail);
  }
  return res.json() as Promise<T>;
}

export const api = {
  get: <T>(path: string) => request<T>("GET", path),
  post: <T>(path: string, body: unknown = {}) => request<T>("POST", path, body),
  patch: <T>(path: string, body: unknown = {}) => request<T>("PATCH", path, body),
  upload: <T>(path: string, form: FormData) => request<T>("POST", path, undefined, form),
};

export async function streamUrl(): Promise<string> {
  const cred = await source();
  const q = new URLSearchParams(cred.query);
  return `/api/stream?${q.toString()}`;
}
