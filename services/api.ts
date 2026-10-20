import { getToken } from "@/utils/storage";

const API_ROOT = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export function apiUrl(path: string): string {
  const suffix = path.startsWith("/") ? path : `/${path}`;
  return `${API_ROOT}/api/v1${suffix}`;
}

export function authHeaders(extra?: HeadersInit): HeadersInit {
  const token = getToken();
  return {
    ...(extra || {}),
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  };
}

export async function readError(response: Response, fallback: string): Promise<string> {
  try {
    const data = await response.json();
    if (typeof data.detail === "string") return data.detail;
    if (Array.isArray(data.detail)) return data.detail.map((item: { msg?: string }) => item.msg).filter(Boolean).join(", ") || fallback;
    return fallback;
  } catch {
    return fallback;
  }
}
