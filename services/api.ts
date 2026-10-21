import { getToken } from "@/utils/storage";

const API_ROOT = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

if (typeof window !== "undefined" && !API_ROOT) {
  console.warn("NEXT_PUBLIC_API_URL environment variable is not set, using default: http://localhost:8000");
}

if (typeof window !== "undefined" && API_ROOT && !API_ROOT.startsWith("http://") && !API_ROOT.startsWith("https://")) {
  console.warn("NEXT_PUBLIC_API_URL must start with http:// or https://");
}

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
