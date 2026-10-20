"use client";

interface RoleBadgeProps {
  role: string;
}

export function RoleBadge({ role }: RoleBadgeProps) {
  const isAdmin = role === "admin";
  return (
    <span
      className={`inline-flex text-xs font-medium px-2 py-0.5 rounded-full ${
        isAdmin ? "bg-amber-100 text-amber-800" : "bg-indigo-100 text-indigo-700"
      }`}
    >
      {role}
    </span>
  );
}
