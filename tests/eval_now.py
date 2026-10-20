"""
Quick evaluation right after ingesting the NSFW Guard PDF.
Just paste the document_id and run.
"""

from app.evaluation import RAGASEvaluator
from app.retrieve import retrieve
from app.llm import generate_answer   # adjust import if your function name is different

# ========== PASTE YOUR DOCUMENT ID HERE ==========
DOCUMENT_ID = "paste-the-uuid-you-got-from-ingest-here"
# =================================================

# Questions + Ground Truth (you can edit these)
TEST_CASES = [
    {
        "question": "What is NSFW Guard?",
        "ground_truth": "NSFW Guard is an explainable nudity detection system for images and videos that uses ONNX Runtime for fully local inference, combines detector and classifier with a consensus mechanism, and provides heatmap visualization."
    },
    {
        "question": "What are the main contributions of the paper?",
        "ground_truth": "The main contributions are a consensus-based NSFW decision framework, an adaptive video frame scanning strategy, a privacy-preserving local inference pipeline, and explainable heatmap-based output visualization."
    },
    {
        "question": "How does the consensus mechanism work?",
        "ground_truth": "The consensus mechanism combines high detector confidence, high classifier unsafe probability, and combined moderate signals to decide NSFW status and reduce false positives and false negatives."
    },
    {
        "question": "What is the adaptive frame sampling strategy?",
        "ground_truth": "It uses adaptive frame sampling, end-weighted scanning, timeout-based termination, and peak confidence tracking to efficiently process long videos."
    },
    {
        "question": "How does the heatmap explainability work?",
        "ground_truth": "Heatmaps are generated from detector bounding boxes and confidence scores. Red regions show high-confidence explicit detections and yellow regions show sensitive but non-explicit areas. OpenCV is used for the overlay."
    },
    {
        "question": "What evaluation metrics were used in the paper?",
        "ground_truth": "Precision, Recall, and False Positive Rate (FPR)."
    },
    {
        "question": "What are the main limitations of NSFW Guard?",
        "ground_truth": "Contextual ambiguity, edge cases with artistic or stylized content, threshold sensitivity, and hardware dependence."
    },
]

def main():
    evaluator = RAGASEvaluator()
    
    print(f"Evaluating on document: {DOCUMENT_ID}\n")
    
    all_scores = []
    
    for i, case in enumerate(TEST_CASES, 1):
        print(f"[{i}/{len(TEST_CASES)}] {case['question']}")
        
        # Real retrieval + generation
        result = retrieve(case["question"], document_id=DOCUMENT_ID)
        answer, llm_skipped = generate_answer(case["question"], result["context"])
        
        print(f"   Answer: {answer[:120]}...")
        
        # RAGAS evaluation
        scores = evaluator.evaluate_single(
            question=case["question"],
            answer=answer,
            contexts=[result["context"]],
            ground_truth=case["ground_truth"],
        )
        
        print(f"   Scores: {scores}\n")
        all_scores.append(scores)
    
    # Average summary
    print("=" * 50)
    print("AVERAGE SCORES")
    print("=" * 50)
    
    metrics = ["faithfulness", "answer_relevancy", "context_precision", "context_recall"]
    for metric in metrics:
        values = [s.get(metric, 0) for s in all_scores if metric in s]
        if values:
            avg = sum(values) / len(values)
            print(f"{metric:25}: {avg:.3f}")

if __name__ == "__main__":
    main()
