import { jsPDF } from "jspdf";
import type { QueryHistoryItem } from "@/types/query";

export function exportQueryHistoryPdf(history: QueryHistoryItem[]): void {
  const pdf = new jsPDF();
  pdf.setFontSize(20);
  pdf.text("Query History", 105, 20, { align: "center" });
  pdf.setFontSize(10);
  pdf.text(`Exported on ${new Date().toLocaleString()}`, 105, 30, { align: "center" });

  let yPosition = 50;
  history.forEach((query, index) => {
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
}
