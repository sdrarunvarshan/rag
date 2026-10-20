import type { User } from "@/types/auth";

const TOKEN_KEY = "token";
const USER_KEY = "user";
const DARK_MODE_KEY = "darkMode";

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem(TOKEN_KEY);
}

export function getStoredUser(): User | null {
  if (typeof window === "undefined") return null;
  const raw = localStorage.getItem(USER_KEY);
  if (!raw) return null;
  try {
    return JSON.parse(raw) as User;
  } catch {
    return null;
  }
}

export function saveSession(token: string, user: User): void {
  localStorage.setItem(TOKEN_KEY, token);
  localStorage.setItem(USER_KEY, JSON.stringify(user));
}

export function clearSession(): void {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(USER_KEY);
}

export function readDarkMode(): boolean {
  if (typeof window === "undefined") return false;
  return localStorage.getItem(DARK_MODE_KEY) === "true";
}

export function writeDarkMode(enabled: boolean): void {
  localStorage.setItem(DARK_MODE_KEY, String(enabled));
  document.documentElement.classList.toggle("dark", enabled);
}
