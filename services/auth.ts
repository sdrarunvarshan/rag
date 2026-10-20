import type { AuthResponse } from "@/types/auth";
import { apiUrl, readError } from "@/services/api";
import { saveSession } from "@/utils/storage";

export async function login(email: string, password: string): Promise<AuthResponse> {
  const response = await fetch(apiUrl("/auth/login"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  });
  if (!response.ok) {
    throw new Error(await readError(response, "Login failed"));
  }
  const data = (await response.json()) as AuthResponse;
  saveSession(data.access_token, data.user);
  return data;
}

export async function register(email: string, password: string, fullName?: string): Promise<AuthResponse> {
  const response = await fetch(apiUrl("/auth/register"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password, full_name: fullName }),
  });
  if (!response.ok) {
    throw new Error(await readError(response, "Registration failed"));
  }
  return (await response.json()) as AuthResponse;
}
