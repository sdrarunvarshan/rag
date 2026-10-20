"""
RAGAS evaluation module for assessing RAG system performance.
Provides metrics for faithfulness, answer relevance, context precision, etc.
"""

from typing import List, Dict, Any, Optional
from datasets import Dataset
from ragas import evaluate
from ragas.metrics import (
    faithfulness,
    answer_relevance,
    context_precision,
    context_recall,
)
from langchain_openai import ChatOpenAI

from app.config import get_settings


class RAGASEvaluator:
    """
    RAGAS evaluation wrapper for RAG system assessment.
    """
    
    def __init__(self, llm: Optional[ChatOpenAI] = None):
        """
        Initialize RAGAS evaluator.
        
        Args:
            llm: LangChain ChatOpenAI instance for evaluation
                 If None, creates one from settings
        """
        settings = get_settings()
        
        if llm is None:
            llm = ChatOpenAI(
                model=settings.openai_model,
                api_key=settings.llm_api_key,
                base_url=settings.openai_base_url,
                temperature=0.0,  # Use deterministic temperature for evaluation
            )
        
        self.llm = llm
        self.metrics = [
            faithfulness,
            answer_relevance,
            context_precision,
            context_recall,
        ]
    
    def evaluate_dataset(
        self,
        questions: List[str],
        answers: List[str],
        contexts: List[List[str]],
        ground_truths: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Evaluate a dataset of Q&A pairs.
        
        Args:
            questions: List of user questions
            answers: List of generated answers
            contexts: List of retrieved contexts for each question
            ground_truths: Optional list of ground truth answers for context_recall
        
        Returns:
            Dictionary with evaluation scores
        """
        # Create dataset dictionary
        dataset_dict = {
            "question": questions,
            "answer": answers,
            "contexts": contexts,
        }
        
        if ground_truths:
            dataset_dict["ground_truth"] = ground_truths
        
        # Create HuggingFace dataset
        dataset = Dataset.from_dict(dataset_dict)
        
        # Run evaluation
        result = evaluate(
            dataset=dataset,
            metrics=self.metrics,
            llm=self.llm,
        )
        
        # Convert to dictionary
        return result.to_pandas().to_dict(orient="records")
    
    def evaluate_single(
        self,
        question: str,
        answer: str,
        contexts: List[str],
        ground_truth: Optional[str] = None,
    ) -> Dict[str, float]:
        """
        Evaluate a single Q&A pair.
        
        Args:
            question: User question
            answer: Generated answer
            contexts: Retrieved contexts
            ground_truth: Optional ground truth answer
        
        Returns:
            Dictionary with metric scores
        """
        return self.evaluate_dataset(
            questions=[question],
            answers=[answer],
            contexts=[contexts],
            ground_truths=[ground_truth] if ground_truth else None,
        )[0]
    
    def get_metrics_summary(self, results: List[Dict[str, Any]]) -> Dict[str, float]:
        """
        Calculate summary statistics from evaluation results.
        
        Args:
            results: List of individual evaluation results
        
        Returns:
            Dictionary with average scores per metric
        """
        summary = {}
        
        for metric in ["faithfulness", "answer_relevancy", "context_precision", "context_recall"]:
            values = [r.get(metric, 0) for r in results if metric in r]
            if values:
                summary[f"avg_{metric}"] = sum(values) / len(values)
        
        return summary


def create_sample_evaluation() -> Dict[str, Any]:
    """
    Create a sample evaluation to test RAGAS setup.
    
    Returns:
        Sample evaluation results
    """
    evaluator = RAGASEvaluator()
    
    # Sample data
    questions = [
        "What is the structure-aware chunking approach?",
        "How does query understanding work?",
    ]
    
    answers = [
        "Structure-aware chunking uses Docling to parse PDFs into heading/table trees and indexes at section, subsection, and table granularity without fixed-size token chunking.",
        "Query understanding classifies query type, scope, and concepts to drive expansion and BM25 query shaping.",
    ]
    
    contexts = [
        [
            "PDF documents are parsed with Docling into a heading / table tree and indexed at section, subsection, and table granularity. There is no fixed-size token chunking.",
            "Structure-aware ingest (headings and tables, not sliding-window chunks)",
        ],
        [
            "Query Understanding: Classifies query type, scope, concepts; sets expansion flags",
            "Query understanding (type, scope, concepts) drives expansion and BM25 query shaping",
        ],
    ]
    
    ground_truths = [
        "Structure-aware chunking uses Docling to parse PDFs into heading/table trees and indexes at section, subsection, and table granularity without fixed-size token chunking.",
        "Query understanding classifies query type, scope, and concepts to drive expansion and BM25 query shaping.",
    ]
    
    results = evaluator.evaluate_dataset(
        questions=questions,
        answers=answers,
        contexts=contexts,
        ground_truths=ground_truths,
    )
    
    summary = evaluator.get_metrics_summary(results)
    
    return {
        "individual_results": results,
        "summary": summary,
    }


if __name__ == "__main__":
    # Test RAGAS evaluation
    print("Running RAGAS evaluation test...")
    try:
        results = create_sample_evaluation()
        print("Evaluation completed successfully!")
        print(f"Summary: {results['summary']}")
    except Exception as e:
        print(f"Evaluation failed: {e}")
