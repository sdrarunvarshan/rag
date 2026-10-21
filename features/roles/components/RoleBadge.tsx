"use client";

interface RoleBadgeProps {
  role: string;
  darkMode?: boolean;
}

export function RoleBadge({ role, darkMode = false }: RoleBadgeProps) {
  const isAdmin = role === "admin";
  return (
    <span
      className={`inline-flex text-xs font-medium px-2 py-0.5 rounded-full ${
        isAdmin
          ? darkMode
            ? "bg-amber-900 text-amber-200"
            : "bg-amber-100 text-amber-800"
          : darkMode
            ? "bg-indigo-900 text-indigo-200"
            : "bg-indigo-100 text-indigo-700"
      }`}
    >
      {role}
    </span>
  );
}
