import { jsPDF } from "jspdf";
import type { QueryHistoryItem } from "@/types/query";

const PAGE_MARGIN = 20;
const PAGE_WIDTH = 210;
const CONTENT_WIDTH = PAGE_WIDTH - (PAGE_MARGIN * 2);
const PAGE_HEIGHT = 297;
const BOTTOM_MARGIN = 20;

function checkPageBreak(pdf: jsPDF, yPosition: number, requiredSpace: number = 20): number {
  if (yPosition + requiredSpace > PAGE_HEIGHT - BOTTOM_MARGIN) {
    pdf.addPage();
    return PAGE_MARGIN;
  }
  return yPosition;
}

export function exportQueryHistoryPdf(history: QueryHistoryItem[]): void {
  const pdf = new jsPDF();
  pdf.setFontSize(20);
  pdf.text("Query History", PAGE_WIDTH / 2, 20, { align: "center" });
  pdf.setFontSize(10);
  pdf.text(`Exported on ${new Date().toLocaleString()}`, PAGE_WIDTH / 2, 30, { align: "center" });

  let yPosition = 50;

  history.forEach((query, index) => {
    yPosition = checkPageBreak(pdf, yPosition, 60);

    pdf.setFontSize(12);
    pdf.setFont("helvetica", "bold");
    const questionLines = pdf.splitTextToSize(`Q${index + 1}: ${query.question}`, CONTENT_WIDTH);
    questionLines.forEach((line: string) => {
      yPosition = checkPageBreak(pdf, yPosition, 10);
      pdf.text(line, PAGE_MARGIN, yPosition);
      yPosition += 7;
    });

    yPosition += 5;

    pdf.setFontSize(10);
    pdf.setFont("helvetica", "normal");
    pdf.text(`Date: ${new Date(query.created_at).toLocaleString()}`, PAGE_MARGIN, yPosition);
    yPosition += 10;

    if (query.answer) {
      pdf.setFont("helvetica", "italic");
      const answerLines = pdf.splitTextToSize(query.answer, CONTENT_WIDTH);
      answerLines.forEach((line: string) => {
        yPosition = checkPageBreak(pdf, yPosition, 7);
        pdf.text(line, PAGE_MARGIN, yPosition);
        yPosition += 5;
      });
      pdf.setFont("helvetica", "normal");
    }

    yPosition += 15;

    if (index < history.length - 1) {
      pdf.setDrawColor(200);
      pdf.line(PAGE_MARGIN, yPosition, PAGE_WIDTH - PAGE_MARGIN, yPosition);
      yPosition += 10;
    }
  });

  pdf.save("query-history.pdf");
}
