"use client";

import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import { jsPDF } from "jspdf";

export default function DashboardPage() {
  const router = useRouter();
  const [user, setUser] = useState<any>(null);
  const [documents, setDocuments] = useState<any[]>([]);
  const [queryHistory, setQueryHistory] = useState<any[]>([]);
  const [question, setQuestion] = useState("");
  const [selectedDocument, setSelectedDocument] = useState<string>("");
  const [answer, setAnswer] = useState("");
  const [streamingAnswer, setStreamingAnswer] = useState("");
  const [streamStatus, setStreamStatus] = useState<"idle" | "retrieving" | "generating" | "done" | "error">("idle");
  const [loading, setLoading] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [activeTab, setActiveTab] = useState<"query" | "stream" | "documents" | "history">("query");
  const [error, setError] = useState("");
  const [darkMode, setDarkMode] = useState(false);
  const [exportingPdf, setExportingPdf] = useState(false);

  const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

  // Dark mode effect
  useEffect(() => {
    const isDark = localStorage.getItem("darkMode") === "true";
    setDarkMode(isDark);
    if (isDark) {
      document.documentElement.classList.add("dark");
    }
  }, []);

  const toggleDarkMode = () => {
    const newMode = !darkMode;
    setDarkMode(newMode);
    localStorage.setItem("darkMode", String(newMode));
    if (newMode) {
      document.documentElement.classList.add("dark");
    } else {
      document.documentElement.classList.remove("dark");
    }
  };

  useEffect(() => {
    const token = localStorage.getItem("token");
    const userData = localStorage.getItem("user");
    if (!token) {
      router.push("/login");
      return;
    }
    if (userData) {
      setUser(JSON.parse(userData));
    }
    fetchDocuments();
    fetchQueryHistory();
  }, [router]);

  const fetchDocuments = async () => {
    const token = localStorage.getItem("token");
    try {
      const response = await fetch(`${API_URL}/documents`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (response.ok) {
        const data = await response.json();
        setDocuments(data);
      }
    } catch (err) {
      console.error("Failed to fetch documents:", err);
    }
  };

  const fetchQueryHistory = async () => {
    const token = localStorage.getItem("token");
    try {
      const response = await fetch(`${API_URL}/query-history`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (response.ok) {
        const data = await response.json();
        setQueryHistory(data.history || []);
      }
    } catch (err) {
      console.error("Failed to fetch query history:", err);
    }
  };

  const handleQuery = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setAnswer("");
    setLoading(true);

    const token = localStorage.getItem("token");
    try {
      const response = await fetch(`${API_URL}/query`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({ 
          question,
          document_id: selectedDocument || undefined,
        }),
      });

      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.detail || "Query failed");
      }

      setAnswer(data.answer || "No answer generated");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Query failed");
    } finally {
      setLoading(false);
    }
  };

  const handleStreamQuery = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setStreamingAnswer("");
    setStreamStatus("retrieving");
    setLoading(true);

    const token = localStorage.getItem("token");
    
    try {
      const response = await fetch(`${API_URL}/query/stream`, {
        method: "POST",
        headers: {
          "Content-Type": "event-stream",
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({ 
          question,
          document_id: selectedDocument || undefined,
        }),
      });

      if (!response.ok) {
        throw new Error("Stream request failed");
      }

      const reader = response.body?.getReader();
      if (!reader) {
        throw new Error("Response body is not readable");
      }

      const decoder = new TextDecoder();
      
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        
        const chunk = decoder.decode(value);
        const lines = chunk.split('\n\n');
        
        for (const line of lines) {
          if (line.startsWith('data: ')) {
            try {
              const data = JSON.parse(line.slice(6));
              
              if (data.event === 'retrieved') {
                setStreamStatus('generating');
                setStreamingAnswer(`📚 Retrieved ${data.sources?.length || 0} sources...`);
              } else if (data.event === 'token') {
                setStreamStatus('generating');
                setStreamingAnswer(prev => prev + data.text);
              } else if (data.event === 'done') {
                setStreamStatus('done');
                setStreamingAnswer(data.answer || "No answer generated");
              } else if (data.event === 'error') {
                setStreamStatus('error');
                setError(data.detail || 'An error occurred');
              }
            } catch (err) {
              console.error('Failed to parse SSE data:', err);
            }
          }
        }
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Stream failed");
      setStreamStatus("error");
    } finally {
      setLoading(false);
    }
  };

  const handleUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    if (!file.name.toLowerCase().endsWith(".pdf")) {
      setError("Please upload a PDF file");
      return;
    }

    setUploading(true);
    setUploadProgress(0);
    setError("");

    const token = localStorage.getItem("token");
    const formData = new FormData();
    formData.append("file", file);

    try {
      const response = await fetch(`${API_URL}/ingest`, {
        method: "POST",
        headers: { Authorization: `Bearer ${token}` },
        body: formData,
      });

      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.detail || "Upload failed");
      }

      setUploadProgress(100);
      setTimeout(() => {
        setUploading(false);
        setUploadProgress(0);
        fetchDocuments();
      }, 1000);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Upload failed");
      setUploading(false);
      setUploadProgress(0);
    }
  };

  const handleDelete = async (documentId: string) => {
    if (!confirm("Are you sure you want to delete this document?")) return;

    const token = localStorage.getItem("token");
    try {
      const response = await fetch(`${API_URL}/documents/${documentId}`, {
        method: "DELETE",
        headers: { Authorization: `Bearer ${token}` },
      });

      if (response.ok) {
        fetchDocuments();
      } else {
        const data = await response.json();
        setError(data.detail || "Delete failed");
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Delete failed");
    }
  };

  const handleDeleteQuery = async (queryId: string) => {
    if (!confirm("Are you sure you want to delete this query from history?")) return;

    const token = localStorage.getItem("token");
    try {
      const response = await fetch(`${API_URL}/query-history/${queryId}`, {
        method: "DELETE",
        headers: { Authorization: `Bearer ${token}` },
      });

      if (response.ok) {
        fetchQueryHistory();
      } else {
        const data = await response.json();
        setError(data.detail || "Delete failed");
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Delete failed");
    }
  };

  const handleExportPdf = async () => {
    setExportingPdf(true);
    try {
      const pdf = new jsPDF();
      
      // Title
      pdf.setFontSize(20);
      pdf.text("Query History", 105, 20, { align: "center" });
      pdf.setFontSize(10);
      pdf.text(`Exported on ${new Date().toLocaleString()}`, 105, 30, { align: "center" });
      
      // Queries
      let yPosition = 50;
      queryHistory.forEach((query, index) => {
        if (yPosition > 270) {
          pdf.addPage();
          yPosition = 20;
        }
        
        pdf.setFontSize(12);
        pdf.text(`Q${index + 1}: ${query.question}`, 20, yPosition);
        yPosition += 10;
        
        pdf.setFontSize(10);
        pdf.setFont("helvetica", "italic");
        const answerLines = pdf.splitTextToSize(query.answer || "No answer", 170);
        answerLines.forEach((line: string) => {
          if (yPosition > 280) {
            pdf.addPage();
            yPosition = 20;
          }
          pdf.text(line, 20, yPosition);
          yPosition += 5;
        });
        
        pdf.setFont("helvetica", "normal");
        pdf.text(`Date: ${new Date(query.created_at).toLocaleString()}`, 20, yPosition);
        yPosition += 15;
      });
      
      pdf.save("query-history.pdf");
    } catch (err) {
      setError("Failed to export PDF");
    } finally {
      setExportingPdf(false);
    }
  };

  const handleLogout = () => {
    localStorage.removeItem("token");
    localStorage.removeItem("user");
    router.push("/");
  };

  return (
    <div className={`min-h-screen ${darkMode ? "bg-gray-900" : "bg-gray-50"}`}>
      {/* Header */}
      <header className={`${darkMode ? "bg-gray-800" : "bg-white"} shadow-sm`}>
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-4">
          <div className="flex justify-between items-center">
            <h1 className={`text-2xl font-bold ${darkMode ? "text-white" : "text-gray-900"}`}>
              Structure-Aware RAG
            </h1>
            <div className="flex items-center gap-4">
              <button
                onClick={toggleDarkMode}
                className={`p-2 rounded-lg ${darkMode ? "bg-gray-700 text-yellow-400" : "bg-gray-100 text-gray-600"}`}
                title="Toggle Dark Mode"
              >
                {darkMode ? "☀️" : "🌙"}
              </button>
              <span className={`text-sm ${darkMode ? "text-gray-300" : "text-gray-600"}`}>
                {user?.email}
              </span>
              <button
                onClick={handleLogout}
                className="text-sm text-red-600 hover:text-red-700 font-medium"
              >
                Logout
              </button>
            </div>
          </div>
        </div>
      </header>

      {/* Main Content */}
      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {/* Tabs */}
        <div className="flex gap-4 mb-6">
          <button
            onClick={() => setActiveTab("query")}
            className={`px-4 py-2 rounded-lg font-medium transition ${
              activeTab === "query"
                ? "bg-indigo-600 text-white"
                : darkMode
                ? "bg-gray-800 text-gray-300 hover:bg-gray-700"
                : "bg-white text-gray-700 hover:bg-gray-100"
            }`}
          >
            Query Documents
          </button>
          <button
            onClick={() => setActiveTab("stream")}
            className={`px-4 py-2 rounded-lg font-medium transition ${
              activeTab === "stream"
                ? "bg-indigo-600 text-white"
                : darkMode
                ? "bg-gray-800 text-gray-300 hover:bg-gray-700"
                : "bg-white text-gray-700 hover:bg-gray-100"
            }`}
          >
            Stream Query (Real-time)
          </button>
          <button
            onClick={() => setActiveTab("documents")}
            className={`px-4 py-2 rounded-lg font-medium transition ${
              activeTab === "documents"
                ? "bg-indigo-600 text-white"
                : darkMode
                ? "bg-gray-800 text-gray-300 hover:bg-gray-700"
                : "bg-white text-gray-700 hover:bg-gray-100"
            }`}
          >
            My Documents ({documents.length})
          </button>
          <button
            onClick={() => setActiveTab("history")}
            className={`px-4 py-2 rounded-lg font-medium transition ${
              activeTab === "history"
                ? "bg-indigo-600 text-white"
                : darkMode
                ? "bg-gray-800 text-gray-300 hover:bg-gray-700"
                : "bg-white text-gray-700 hover:bg-gray-100"
            }`}
          >
            Query History ({queryHistory.length})
          </button>
        </div>

        {error && (
          <div className="mb-4 p-3 bg-red-50 border border-red-200 text-red-700 rounded-lg text-sm">
            {error}
          </div>
        )}

        {/* Query Tab */}
        {activeTab === "query" && (
          <div className="space-y-6">
            <div className={`${darkMode ? "bg-gray-800" : "bg-white"} rounded-xl shadow-sm p-6`}>
              <h2 className={`text-xl font-semibold ${darkMode ? "text-white" : "text-gray-900"} mb-4`}>
                Ask a Question
              </h2>
              
              {/* Advanced Search Filters */}
              <div className="mb-4 p-4 bg-gray-50 rounded-lg">
                <label className="block text-sm font-medium text-gray-700 mb-2">
                  Filter by Document (Optional)
                </label>
                <select
                  value={selectedDocument}
                  onChange={(e) => setSelectedDocument(e.target.value)}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-500 bg-white"
                >
                  <option value="">All Documents</option>
                  {documents.map((doc) => (
                    <option key={doc.id} value={doc.id}>
                      {doc.filename}
                    </option>
                  ))}
                </select>
              </div>

              <form onSubmit={handleQuery} className="space-y-4">
                <textarea
                  value={question}
                  onChange={(e) => setQuestion(e.target.value)}
                  required
                  rows={3}
                  className={`w-full px-3 py-2 border rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-500 ${
                    darkMode
                      ? "bg-gray-700 border-gray-600 text-white"
                      : "border-gray-300"
                  }`}
                  placeholder="Ask a question about your documents..."
                />
                <button
                  type="submit"
                  disabled={loading}
                  className="bg-indigo-600 hover:bg-indigo-700 disabled:bg-indigo-400 text-white font-semibold py-2 px-6 rounded-lg transition duration-200"
                >
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

            <div className={`${darkMode ? "bg-gray-800" : "bg-white"} rounded-xl shadow-sm p-6`}>
              <h2 className={`text-xl font-semibold ${darkMode ? "text-white" : "text-gray-900"} mb-4`}>
                System Health
              </h2>
              <div className="flex gap-4">
                <button
                  onClick={async () => {
                    const res = await fetch(`${API_URL}/health`);
                    const data = await res.json();
                    alert(`Health: ${JSON.stringify(data, null, 2)}`);
                  }}
                  className="px-4 py-2 bg-green-600 hover:bg-green-700 text-white rounded-lg font-medium"
                >
                  Check Health
                </button>
                <button
                  onClick={async () => {
                    const res = await fetch(`${API_URL}/ready`);
                    const data = await res.json();
                    alert(`Readiness: ${JSON.stringify(data, null, 2)}`);
                  }}
                  className="px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded-lg font-medium"
                >
                  Check Readiness
                </button>
              </div>
            </div>
          </div>
        )}

        {/* Stream Query Tab */}
        {activeTab === "stream" && (
          <div className="space-y-6">
            <div className={`${darkMode ? "bg-gray-800" : "bg-white"} rounded-xl shadow-sm p-6`}>
              <h2 className={`text-xl font-semibold ${darkMode ? "text-white" : "text-gray-900"} mb-4`}>
                Stream Query (Real-time)
              </h2>
              
              {/* Advanced Search Filters */}
              <div className="mb-4 p-4 bg-gray-50 rounded-lg">
                <label className="block text-sm font-medium text-gray-700 mb-2">
                  Filter by Document (Optional)
                </label>
                <select
                  value={selectedDocument}
                  onChange={(e) => setSelectedDocument(e.target.value)}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-500 bg-white"
                >
                  <option value="">All Documents</option>
                  {documents.map((doc) => (
                    <option key={doc.id} value={doc.id}>
                      {doc.filename}
                    </option>
                  ))}
                </select>
              </div>

              <form onSubmit={handleStreamQuery} className="space-y-4">
                <textarea
                  value={question}
                  onChange={(e) => setQuestion(e.target.value)}
                  required
                  rows={3}
                  className={`w-full px-3 py-2 border rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-500 ${
                    darkMode
                      ? "bg-gray-700 border-gray-600 text-white"
                      : "border-gray-300"
                  }`}
                  placeholder="Ask a question about your documents..."
                />
                <button
                  type="submit"
                  disabled={loading}
                  className="bg-indigo-600 hover:bg-indigo-700 disabled:bg-indigo-400 text-white font-semibold py-2 px-6 rounded-lg transition duration-200"
                >
                  {loading ? "Streaming..." : "Stream Ask"}
                </button>
              </form>

              {/* Stream Status */}
              {streamStatus !== "idle" && (
                <div className="mt-6 p-4 bg-indigo-50 border border-indigo-200 rounded-lg">
                  <div className="flex items-center gap-2 mb-2">
                    <h3 className="font-semibold text-gray-900">Status:</h3>
                    <span className={`text-sm font-medium ${
                      streamStatus === "retrieving" ? "text-blue-600" :
                      streamStatus === "generating" ? "text-green-600" :
                      streamStatus === "done" ? "text-indigo-600" :
                      "text-red-600"
                    }`}>
                      {streamStatus === "retrieving" && "🔍 Retrieving context..."}
                      {streamStatus === "generating" && "✨ Generating answer..."}
                      {streamStatus === "done" && "✅ Complete"}
                      {streamStatus === "error" && "❌ Error"}
                    </span>
                  </div>
                  {streamingAnswer && (
                    <p className="text-gray-700 whitespace-pre-wrap">{streamingAnswer}</p>
                  )}
                </div>
              )}
            </div>
          </div>
        )}

        {/* Documents Tab */}
        {activeTab === "documents" && (
          <div className="space-y-6">
            <div className={`${darkMode ? "bg-gray-800" : "bg-white"} rounded-xl shadow-sm p-6`}>
              <h2 className={`text-xl font-semibold ${darkMode ? "text-white" : "text-gray-900"} mb-4`}>
                Upload Document
              </h2>
              <div className="border-2 border-dashed border-gray-300 rounded-lg p-8 text-center">
                <input
                  type="file"
                  accept=".pdf"
                  onChange={handleUpload}
                  disabled={uploading}
                  className="hidden"
                  id="file-upload"
                />
                <label
                  htmlFor="file-upload"
                  className="cursor-pointer"
                >
                  <div className="text-gray-600 mb-2">
                    {uploading ? (
                      <div>
                        <div className="text-lg font-semibold mb-2">
                          Uploading... {uploadProgress}%
                        </div>
                        <div className="w-full bg-gray-200 rounded-full h-2">
                          <div
                            className="bg-indigo-600 h-2 rounded-full transition-all"
                            style={{ width: `${uploadProgress}%` }}
                          />
                        </div>
                      </div>
                    ) : (
                      <>
                        <p className="text-lg font-semibold">
                          Click to upload PDF
                        </p>
                        <p className="text-sm">or drag and drop</p>
                      </>
                    )}
                  </div>
                </label>
              </div>
            </div>

            <div className={`${darkMode ? "bg-gray-800" : "bg-white"} rounded-xl shadow-sm p-6`}>
              <h2 className={`text-xl font-semibold ${darkMode ? "text-white" : "text-gray-900"} mb-4`}>
                My Documents
              </h2>
              {documents.length === 0 ? (
                <p className="text-gray-500 text-center py-8">
                  No documents uploaded yet
                </p>
              ) : (
                <div className="space-y-3">
                  {documents.map((doc) => (
                    <div
                      key={doc.id}
                      className={`flex items-center justify-between p-4 rounded-lg ${darkMode ? "bg-gray-700" : "bg-gray-50"}`}
                    >
                      <div>
                        <p className={`font-medium ${darkMode ? "text-white" : "text-gray-900"}`}>
                          {doc.filename}
                        </p>
                        <p className={`text-sm ${darkMode ? "text-gray-400" : "text-gray-500"}`}>
                          Uploaded: {new Date(doc.created_at).toLocaleDateString()}
                        </p>
                      </div>
                      <button
                        onClick={() => handleDelete(doc.id)}
                        className="text-red-600 hover:text-red-700 font-medium"
                      >
                        Delete
                      </button>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        )}

        {/* History Tab */}
        {activeTab === "history" && (
          <div className="space-y-6">
            <div className={`${darkMode ? "bg-gray-800" : "bg-white"} rounded-xl shadow-sm p-6`}>
              <div className="flex justify-between items-center mb-4">
                <h2 className={`text-xl font-semibold ${darkMode ? "text-white" : "text-gray-900"}`}>
                  Query History
                </h2>
                <button
                  onClick={handleExportPdf}
                  disabled={exportingPdf || queryHistory.length === 0}
                  className="px-4 py-2 bg-indigo-600 hover:bg-indigo-700 disabled:bg-indigo-400 text-white rounded-lg font-medium"
                >
                  {exportingPdf ? "Exporting..." : "Export as PDF"}
                </button>
              </div>
              {queryHistory.length === 0 ? (
                <p className="text-gray-500 text-center py-8">
                  No queries yet. Ask a question to see it here.
                </p>
              ) : (
                <div className="space-y-4">
                  {queryHistory.map((query) => (
                    <div
                      key={query.id}
                      className={`p-4 rounded-lg ${darkMode ? "bg-gray-700" : "bg-gray-50"}`}
                    >
                      <div className="flex justify-between items-start mb-2">
                        <div className="flex-1">
                          <p className={`font-medium ${darkMode ? "text-white" : "text-gray-900"} mb-1`}>
                            {query.question}
                          </p>
                          <p className={`text-sm ${darkMode ? "text-gray-400" : "text-gray-500"} mb-2`}>
                            {new Date(query.created_at).toLocaleString()}
                          </p>
                        </div>
                        <button
                          onClick={() => handleDeleteQuery(query.id)}
                          className="text-red-600 hover:text-red-700 font-medium text-sm"
                        >
                          Delete
                        </button>
                      </div>
                      {query.answer && (
                        <div className="mt-3 p-3 rounded border border-gray-200 bg-white">
                          <p className="text-sm text-gray-700 whitespace-pre-wrap">
                            {query.answer}
                          </p>
                        </div>
                      )}
                      {query.sources && query.sources.length > 0 && (
                        <div className="mt-2">
                          <p className={`text-xs ${darkMode ? "text-gray-400" : "text-gray-500"} font-medium`}>
                            Sources: {query.sources.length}
                          </p>
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        )}
      </main>
    </div>
  );
}
