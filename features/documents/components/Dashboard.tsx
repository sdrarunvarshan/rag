"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { UserMenu } from "@/features/users/components/UserMenu";
import { deleteDocument, listDocuments, uploadDocument } from "@/services/documents";
import { checkHealth, checkReadiness } from "@/services/health";
import { askQuestion, deleteQueryHistory, listQueryHistory, streamQuestion } from "@/services/queries";
import { getCurrentUser } from "@/services/users";
import type { User } from "@/types/auth";
import type { DocumentItem } from "@/types/document";
import type { QueryHistoryItem, StreamStatus } from "@/types/query";
import { exportQueryHistoryPdf } from "@/utils/export-pdf";
import { clearSession, getToken, readDarkMode, writeDarkMode } from "@/utils/storage";

type DashboardTab = "query" | "stream" | "documents" | "history";

export function Dashboard() {
  const router = useRouter();
  const [user, setUser] = useState<User | null>(null);
  const [documents, setDocuments] = useState<DocumentItem[]>([]);
  const [queryHistory, setQueryHistory] = useState<QueryHistoryItem[]>([]);
  const [question, setQuestion] = useState("");
  const [selectedDocument, setSelectedDocument] = useState("");
  const [answer, setAnswer] = useState("");
  const [streamingAnswer, setStreamingAnswer] = useState("");
  const [streamStatus, setStreamStatus] = useState<StreamStatus>("idle");
  const [loading, setLoading] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [activeTab, setActiveTab] = useState<DashboardTab>("query");
  const [error, setError] = useState("");
  const [darkMode, setDarkMode] = useState(false);
  const [exportingPdf, setExportingPdf] = useState(false);

  useEffect(() => {
    const isDark = readDarkMode();
    setDarkMode(isDark);
    if (isDark) document.documentElement.classList.add("dark");
  }, []);

  useEffect(() => {
    if (!getToken()) {
      router.push("/login");
      return;
    }
    getCurrentUser()
      .then(setUser)
      .catch(() => router.push("/login"));
    listDocuments().then(setDocuments).catch((err) => console.error(err));
    listQueryHistory().then(setQueryHistory).catch((err) => console.error(err));
  }, [router]);

  const toggleDarkMode = () => {
    const next = !darkMode;
    setDarkMode(next);
    writeDarkMode(next);
  };

  const handleQuery = async (event: React.FormEvent) => {
    event.preventDefault();
    setError("");
    setAnswer("");
    setLoading(true);
    try {
      setAnswer(await askQuestion(question, selectedDocument));
      setQueryHistory(await listQueryHistory());
    } catch (err) {
      setError(err instanceof Error ? err.message : "Query failed");
    } finally {
      setLoading(false);
    }
  };

  const handleStreamQuery = async (event: React.FormEvent) => {
    event.preventDefault();
    setError("");
    setStreamingAnswer("");
    setStreamStatus("retrieving");
    setLoading(true);
    try {
      await streamQuestion(question, selectedDocument, (data) => {
        if (data.event === "retrieved") {
          setStreamStatus("generating");
          setStreamingAnswer(`Retrieved ${data.sources?.length || 0} sources...`);
        } else if (data.event === "token") {
          setStreamStatus("generating");
          setStreamingAnswer((prev) => (prev.startsWith("Retrieved") ? data.text || "" : prev + (data.text || "")));
        } else if (data.event === "done") {
          setStreamStatus("done");
          setStreamingAnswer(data.answer || "No answer generated");
        } else if (data.event === "error") {
          setStreamStatus("error");
          setError(data.detail || "An error occurred");
        }
      });
      setQueryHistory(await listQueryHistory());
    } catch (err) {
      setError(err instanceof Error ? err.message : "Stream failed");
      setStreamStatus("error");
    } finally {
      setLoading(false);
    }
  };

  const handleUpload = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file) return;
    if (!file.name.toLowerCase().endsWith(".pdf")) {
      setError("Please upload a PDF file");
      return;
    }
    setUploading(true);
    setUploadProgress(30);
    setError("");
    try {
      await uploadDocument(file);
      setUploadProgress(100);
      setDocuments(await listDocuments());
    } catch (err) {
      setError(err instanceof Error ? err.message : "Upload failed");
    } finally {
      setUploading(false);
      setUploadProgress(0);
      event.target.value = "";
    }
  };

  const handleDelete = async (documentId: string) => {
    if (!confirm("Are you sure you want to delete this document?")) return;
    try {
      await deleteDocument(documentId);
      setDocuments(await listDocuments());
    } catch (err) {
      setError(err instanceof Error ? err.message : "Delete failed");
    }
  };

  const handleDeleteQuery = async (queryId: string) => {
    if (!confirm("Are you sure you want to delete this query from history?")) return;
    try {
      await deleteQueryHistory(queryId);
      setQueryHistory(await listQueryHistory());
    } catch (err) {
      setError(err instanceof Error ? err.message : "Delete failed");
    }
  };

  const handleExportPdf = () => {
    setExportingPdf(true);
    try {
      exportQueryHistoryPdf(queryHistory);
    } catch {
      setError("Failed to export PDF");
    } finally {
      setExportingPdf(false);
    }
  };

  const handleLogout = () => {
    clearSession();
    router.push("/");
  };

  const tabClass = (tab: DashboardTab) =>
    `px-4 py-2 rounded-lg font-medium transition ${
      activeTab === tab
        ? "bg-indigo-600 text-white"
        : darkMode
          ? "bg-gray-800 text-gray-300 hover:bg-gray-700"
          : "bg-white text-gray-700 hover:bg-gray-100"
    }`;

  const cardClass = `${darkMode ? "bg-gray-800" : "bg-white"} rounded-xl shadow-sm p-6`;
  const titleClass = `text-xl font-semibold ${darkMode ? "text-white" : "text-gray-900"} mb-4`;

  return (
    <div className={`min-h-screen ${darkMode ? "bg-gray-900" : "bg-gray-50"}`}>
      <header className={`${darkMode ? "bg-gray-800" : "bg-white"} shadow-sm`}>
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-4">
          <div className="flex justify-between items-center">
            <h1 className={`text-2xl font-bold ${darkMode ? "text-white" : "text-gray-900"}`}>Structure-Aware RAG</h1>
            <UserMenu user={user} darkMode={darkMode} onToggleDarkMode={toggleDarkMode} onLogout={handleLogout} />
          </div>
        </div>
      </header>

      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        <div className="flex gap-4 mb-6 flex-wrap">
          <button onClick={() => setActiveTab("query")} className={tabClass("query")}>Query Documents</button>
          <button onClick={() => setActiveTab("stream")} className={tabClass("stream")}>Stream Query (Real-time)</button>
          <button onClick={() => setActiveTab("documents")} className={tabClass("documents")}>My Documents ({documents.length})</button>
          <button onClick={() => setActiveTab("history")} className={tabClass("history")}>Query History ({queryHistory.length})</button>
        </div>

        {error && <div className="mb-4 p-3 bg-red-50 border border-red-200 text-red-700 rounded-lg text-sm">{error}</div>}

        {activeTab === "query" && (
          <div className="space-y-6">
            <div className={cardClass}>
              <h2 className={titleClass}>Ask a Question</h2>
              <DocumentFilter documents={documents} value={selectedDocument} onChange={setSelectedDocument} />
              <form onSubmit={handleQuery} className="space-y-4">
                <textarea
                  value={question}
                  onChange={(event) => setQuestion(event.target.value)}
                  required
                  rows={3}
                  className={`w-full px-3 py-2 border rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-500 ${darkMode ? "bg-gray-700 border-gray-600 text-white" : "border-gray-300"}`}
                  placeholder="Ask a question about your documents..."
                />
                <button type="submit" disabled={loading} className="bg-indigo-600 hover:bg-indigo-700 disabled:bg-indigo-400 text-white font-semibold py-2 px-6 rounded-lg">
                  {loading ? "Processing..." : "Ask"}
                </button>
              </form>
              {answer && (
                <div className="mt-6 p-4 bg-indigo-50 border border-indigo-200 rounded-lg">
                  <h3 className="font-semibold text-gray-900 mb-2">Answer:</h3>
                  <p className="text-gray-700 whitespace-pre-wrap">{answer}</p>
                </div>
              )}
            </div>
            <div className={cardClass}>
              <h2 className={titleClass}>System Health</h2>
              <div className="flex gap-4">
                <button
                  onClick={async () => alert(`Health: ${JSON.stringify(await checkHealth(), null, 2)}`)}
                  className="px-4 py-2 bg-green-600 hover:bg-green-700 text-white rounded-lg font-medium"
                >
                  Check Health
                </button>
                <button
                  onClick={async () => alert(`Readiness: ${JSON.stringify(await checkReadiness(), null, 2)}`)}
                  className="px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded-lg font-medium"
                >
                  Check Readiness
                </button>
              </div>
            </div>
          </div>
        )}

        {activeTab === "stream" && (
          <div className={cardClass}>
            <h2 className={titleClass}>Stream Query (Real-time)</h2>
            <DocumentFilter documents={documents} value={selectedDocument} onChange={setSelectedDocument} />
            <form onSubmit={handleStreamQuery} className="space-y-4">
              <textarea
                value={question}
                onChange={(event) => setQuestion(event.target.value)}
                required
                rows={3}
                className={`w-full px-3 py-2 border rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-500 ${darkMode ? "bg-gray-700 border-gray-600 text-white" : "border-gray-300"}`}
                placeholder="Ask a question about your documents..."
              />
              <button type="submit" disabled={loading} className="bg-indigo-600 hover:bg-indigo-700 disabled:bg-indigo-400 text-white font-semibold py-2 px-6 rounded-lg">
                {loading ? "Streaming..." : "Stream Ask"}
              </button>
            </form>
            {streamStatus !== "idle" && (
              <div className="mt-6 p-4 bg-indigo-50 border border-indigo-200 rounded-lg">
                <h3 className="font-semibold text-gray-900 mb-2">
                  {streamStatus === "retrieving" && "Retrieving context..."}
                  {streamStatus === "generating" && "Generating answer..."}
                  {streamStatus === "done" && "Complete"}
                  {streamStatus === "error" && "Error"}
                </h3>
                {streamingAnswer && <p className="text-gray-700 whitespace-pre-wrap">{streamingAnswer}</p>}
              </div>
            )}
          </div>
        )}

        {activeTab === "documents" && (
          <div className="space-y-6">
            <div className={cardClass}>
              <h2 className={titleClass}>Upload Document</h2>
              <div className="border-2 border-dashed border-gray-300 rounded-lg p-8 text-center">
                <input type="file" accept=".pdf" onChange={handleUpload} disabled={uploading} className="hidden" id="file-upload" />
                <label htmlFor="file-upload" className="cursor-pointer text-gray-600">
                  {uploading ? `Uploading... ${uploadProgress}%` : "Click to upload PDF"}
                </label>
              </div>
            </div>
            <div className={cardClass}>
              <h2 className={titleClass}>My Documents</h2>
              {documents.length === 0 ? (
                <p className="text-gray-500 text-center py-8">No documents uploaded yet</p>
              ) : (
                <div className="space-y-3">
                  {documents.map((doc) => (
                    <div key={doc.id} className={`flex items-center justify-between p-4 rounded-lg ${darkMode ? "bg-gray-700" : "bg-gray-50"}`}>
                      <div>
                        <p className={`font-medium ${darkMode ? "text-white" : "text-gray-900"}`}>{doc.filename}</p>
                        <p className={`text-sm ${darkMode ? "text-gray-400" : "text-gray-500"}`}>
                          Uploaded: {doc.created_at ? new Date(doc.created_at).toLocaleDateString() : "Unknown"}
                        </p>
                      </div>
                      <button onClick={() => handleDelete(doc.id)} className="text-red-600 hover:text-red-700 font-medium">Delete</button>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        )}

        {activeTab === "history" && (
          <div className={cardClass}>
            <div className="flex justify-between items-center mb-4">
              <h2 className={`text-xl font-semibold ${darkMode ? "text-white" : "text-gray-900"}`}>Query History</h2>
              <button
                onClick={handleExportPdf}
                disabled={exportingPdf || queryHistory.length === 0}
                className="px-4 py-2 bg-indigo-600 hover:bg-indigo-700 disabled:bg-indigo-400 text-white rounded-lg font-medium"
              >
                {exportingPdf ? "Exporting..." : "Export as PDF"}
              </button>
            </div>
            {queryHistory.length === 0 ? (
              <p className="text-gray-500 text-center py-8">No queries yet. Ask a question to see it here.</p>
            ) : (
              <div className="space-y-4">
                {queryHistory.map((query) => (
                  <div key={query.id} className={`p-4 rounded-lg ${darkMode ? "bg-gray-700" : "bg-gray-50"}`}>
                    <div className="flex justify-between items-start mb-2">
                      <div>
                        <p className={`font-medium ${darkMode ? "text-white" : "text-gray-900"} mb-1`}>{query.question}</p>
                        <p className={`text-sm ${darkMode ? "text-gray-400" : "text-gray-500"}`}>{new Date(query.created_at).toLocaleString()}</p>
                      </div>
                      <button onClick={() => handleDeleteQuery(query.id)} className="text-red-600 hover:text-red-700 font-medium text-sm">Delete</button>
                    </div>
                    {query.answer && (
                      <div className="mt-3 p-3 rounded border border-gray-200 bg-white">
                        <p className="text-sm text-gray-700 whitespace-pre-wrap">{query.answer}</p>
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </main>
    </div>
  );
}

function DocumentFilter({
  documents,
  value,
  onChange,
}: {
  documents: DocumentItem[];
  value: string;
  onChange: (value: string) => void;
}) {
  return (
    <div className="mb-4 p-4 bg-gray-50 rounded-lg">
      <label className="block text-sm font-medium text-gray-700 mb-2">Filter by Document (Optional)</label>
      <select
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-500 bg-white"
      >
        <option value="">All Documents</option>
        {documents.map((doc) => (
          <option key={doc.id} value={doc.id}>{doc.filename}</option>
        ))}
      </select>
    </div>
  );
}
