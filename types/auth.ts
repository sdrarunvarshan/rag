export type RoleName = "user" | "admin";

export interface User {
  id: string;
  email: string;
  full_name?: string | null;
  created_at?: string | null;
  role?: RoleName | string;
}

export interface AuthResponse {
  access_token: string;
  token_type: string;
  user: User;
}
