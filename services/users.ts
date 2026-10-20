import type { User } from "@/types/auth";
import { apiUrl, authHeaders, readError } from "@/services/api";

export async function getCurrentUser(): Promise<User> {
  const response = await fetch(apiUrl("/users/me"), {
    headers: authHeaders(),
  });
  if (!response.ok) {
    throw new Error(await readError(response, "Could not load the current user"));
  }
  return (await response.json()) as User;
}
