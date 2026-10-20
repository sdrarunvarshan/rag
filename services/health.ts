import { apiUrl } from "@/services/api";

export async function checkHealth(): Promise<unknown> {
  const response = await fetch(apiUrl("/health"));
  return response.json();
}

export async function checkReadiness(): Promise<unknown> {
  const response = await fetch(apiUrl("/ready"));
  return response.json();
}
