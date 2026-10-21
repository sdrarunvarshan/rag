import { apiUrl } from "@/services/api";

export async function checkHealth(): Promise<Record<string, unknown>> {
  const response = await fetch(apiUrl("/health"));
  if (!response.ok) {
    throw new Error(`Health check failed: ${response.status}`);
  }
  return response.json() as Promise<Record<string, unknown>>;
}

export async function checkReadiness(): Promise<Record<string, unknown>> {
  const response = await fetch(apiUrl("/ready"));
  if (!response.ok) {
    throw new Error(`Readiness check failed: ${response.status}`);
  }
  return response.json() as Promise<Record<string, unknown>>;
}
