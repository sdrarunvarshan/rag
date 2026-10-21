"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { getToken } from "@/utils/storage";

const FEATURES = [
  "Structure-aware PDF parsing with Docling",
  "Hybrid search: pgvector + BM25 with RRF fusion",
  "Hierarchical expansion and table retrieval",
  "Multi-tenant isolation with JWT authentication",
  "Image extraction and storage",
  "Durable workflows with Temporal.io",
];

export function HomePage() {
  const router = useRouter();

  useEffect(() => {
    if (getToken()) {
      router.push("/dashboard");
    }
  }, [router]);

  return (
    <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-blue-50 to-indigo-100">
      <div className="max-w-md w-full mx-4">
        <div className="bg-white rounded-2xl shadow-xl p-8">
          <div className="text-center mb-8">
            <h1 className="text-4xl font-bold text-gray-900 mb-2">Structure-Aware RAG</h1>
            <p className="text-gray-600">AI-powered document retrieval with structure-aware indexing</p>
          </div>
          <div className="space-y-4">
            <button
              onClick={() => router.push("/login")}
              className="w-full bg-indigo-600 hover:bg-indigo-700 text-white font-semibold py-3 px-4 rounded-lg transition duration-200"
            >
              Login
            </button>
            <button
              onClick={() => router.push("/register")}
              className="w-full bg-white border-2 border-indigo-600 text-indigo-600 hover:bg-indigo-50 font-semibold py-3 px-4 rounded-lg transition duration-200"
            >
              Register
            </button>
          </div>
          <div className="mt-8 pt-8 border-t border-gray-200">
            <h2 className="text-lg font-semibold text-gray-900 mb-4">Key Features</h2>
            <ul className="space-y-2 text-sm text-gray-600">
              {FEATURES.map((feature) => (
                <li key={feature} className="flex items-start">
                  <span className="text-green-500 mr-2">✓</span>
                  <span>{feature}</span>
                </li>
              ))}
            </ul>
          </div>
        </div>
      </div>
    </div>
  );
}
