"use client";

import type { User } from "@/types/auth";
import { RoleBadge } from "@/features/roles/components/RoleBadge";

interface UserMenuProps {
  user: User | null;
  darkMode: boolean;
  onToggleDarkMode: () => void;
  onLogout: () => void;
}

export function UserMenu({ user, darkMode, onToggleDarkMode, onLogout }: UserMenuProps) {
  return (
    <div className="flex items-center gap-4">
      <button
        onClick={onToggleDarkMode}
        className={`p-2 rounded-lg ${darkMode ? "bg-gray-700 text-yellow-400" : "bg-gray-100 text-gray-600"}`}
        title="Toggle Dark Mode"
      >
        {darkMode ? "☀️" : "🌙"}
      </button>
      <div className="text-right">
        <p className={`text-sm ${darkMode ? "text-gray-300" : "text-gray-600"}`}>{user?.email}</p>
        <RoleBadge role={user?.role || "user"} />
      </div>
      <button onClick={onLogout} className="text-sm text-red-600 hover:text-red-700 font-medium">
        Logout
      </button>
    </div>
  );
}
