import type { Role } from "@/types/role";
import { apiUrl, authHeaders, readError } from "@/services/api";

export async function listRoles(): Promise<Role[]> {
  const response = await fetch(apiUrl("/roles"), {
    headers: authHeaders(),
  });
  if (!response.ok) {
    throw new Error(await readError(response, "Could not load roles"));
  }
  return (await response.json()) as Role[];
}
