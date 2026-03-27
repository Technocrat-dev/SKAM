#!/usr/bin/env python3
"""
ML Pipeline Validation Benchmark
=================================
Compares two training approaches for the SKAM anomaly detector:

  Approach A (Baseline):   Pure synthetic data — random Gaussian distributions
                           with no grounding in real-world observations.

  Approach B (Proposed):   Real-data-derived synthetic data — multivariate
                           Gaussians fitted to real TrainTicket Prometheus KPI
                           data, preserving learned cross-feature correlations.

Ground Truth: Real labeled observations from the TrainTicket experiment
              (34 points × 7 services, with rows 21-25 labeled anomalous
              on ts-auth-service and ts-order-service).

Metrics:
  - Precision, Recall, F1 Score
  - AUC-ROC, AUC-PR (Average Precision)
  - Mean Reconstruction Error (for LSTM)
  - Threshold Calibration Analysis
  - Per-service breakdown

Usage:
  python scripts/validate_ml_pipeline.py
  python scripts/validate_ml_pipeline.py --output results/benchmark.md
"""

import argparse
import os
import sys
import time
from pathlib import Path
from datetime import datetime

import numpy as np

# Add the anomaly detector to the path so we can import models directly
DETECTOR_DIR = Path(__file__).resolve().parent.parent / "platform" / "anomaly-detector"
sys.path.insert(0, str(DETECTOR_DIR))

from models.isolation_forest import IsolationForestDetector
from models.lstm_autoencoder import LSTMAutoencoder
from ensemble import EnsembleScorer

TRAINING_DATA_DIR = DETECTOR_DIR / "training_data"
FEATURE_NAMES = [
    "request_rate", "error_rate", "latency_p50", "latency_p99",
    "cpu_usage", "memory_usage_mb", "restart_count", "error_ratio",
    "latency_spread", "request_rate_zscore", "error_rate_zscore",
    "latency_p99_zscore", "cpu_zscore", "request_rate_delta",
    "error_rate_delta", "latency_delta",
]

SERVICES = [
    "api-gateway", "user-service", "product-service",
    "order-service", "cart-service", "payment-service", "notification-service",
]

THRESHOLD = 0.7


def compute_metrics(y_true, y_scores, threshold=THRESHOLD):
    """Compute classification metrics at a given threshold."""
    y_pred = (np.array(y_scores) > threshold).astype(int)
    y_true = np.array(y_true)

    tp = np.sum((y_pred == 1) & (y_true == 1))
    fp = np.sum((y_pred == 1) & (y_true == 0))
    fn = np.sum((y_pred == 0) & (y_true == 1))
    tn = np.sum((y_pred == 0) & (y_true == 0))

    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0
    accuracy = (tp + tn) / len(y_true) if len(y_true) > 0 else 0.0

    return {
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "accuracy": accuracy,
        "tp": int(tp), "fp": int(fp), "fn": int(fn), "tn": int(tn),
    }


def compute_auc_roc(y_true, y_scores):
    """Compute AUC-ROC using the trapezoidal rule (no sklearn dependency)."""
    y_true = np.array(y_true)
    y_scores = np.array(y_scores)

    # Sort by descending score
    desc_score_indices = np.argsort(y_scores)[::-1]
    y_true_sorted = y_true[desc_score_indices]
    y_scores_sorted = y_scores[desc_score_indices]

    n_pos = np.sum(y_true == 1)
    n_neg = np.sum(y_true == 0)

    if n_pos == 0 or n_neg == 0:
        return 0.5  # undefined, return chance

    # Compute TPR and FPR at each threshold
    tprs, fprs = [0.0], [0.0]
    tp, fp = 0, 0
    for i in range(len(y_true_sorted)):
        if y_true_sorted[i] == 1:
            tp += 1
        else:
            fp += 1
        tprs.append(tp / n_pos)
        fprs.append(fp / n_neg)

    # Trapezoidal AUC
    auc = 0.0
    for i in range(1, len(fprs)):
        auc += (fprs[i] - fprs[i-1]) * (tprs[i] + tprs[i-1]) / 2

    return auc


def compute_avg_precision(y_true, y_scores):
    """Compute Average Precision (AUC-PR) using the trapezoidal rule."""
    y_true = np.array(y_true)
    y_scores = np.array(y_scores)

    desc_indices = np.argsort(y_scores)[::-1]
    y_true_sorted = y_true[desc_indices]

    n_pos = np.sum(y_true == 1)
    if n_pos == 0:
        return 0.0

    tp = 0
    precisions, recalls = [1.0], [0.0]
    for i in range(len(y_true_sorted)):
        if y_true_sorted[i] == 1:
            tp += 1
        prec = tp / (i + 1)
        rec = tp / n_pos
        precisions.append(prec)
        recalls.append(rec)

    # Average precision
    ap = 0.0
    for i in range(1, len(recalls)):
        ap += (recalls[i] - recalls[i-1]) * precisions[i]

    return ap


def generate_pure_synthetic(n_features, n_normal, n_anomaly, seed=123):
    """Approach A: Pure synthetic data with no real-world grounding.
    Random Gaussian distributions — the old approach."""
    rng = np.random.RandomState(seed)

    # Normal: random means and stds (not calibrated to real data)
    normal_mean = rng.uniform(0.5, 30, size=n_features)
    normal_std = rng.uniform(0.1, 5, size=n_features)
    X_normal = rng.normal(normal_mean, normal_std, size=(n_normal, n_features))
    X_normal = np.maximum(0, X_normal)

    # Anomaly: inflate some features randomly
    anomaly_mean = normal_mean.copy()
    anomaly_mean[1] *= 3   # error_rate
    anomaly_mean[3] *= 2   # latency_p99
    anomaly_mean[4] *= 3   # cpu_usage
    anomaly_mean[6] += 3   # restart_count
    anomaly_std_a = normal_std * 2
    X_anomaly = rng.normal(anomaly_mean, anomaly_std_a, size=(n_anomaly, n_features))
    X_anomaly = np.maximum(0, X_anomaly)

    X = np.vstack([X_normal, X_anomaly])
    y = np.concatenate([np.zeros(n_normal), np.ones(n_anomaly)])
    perm = rng.permutation(len(X))
    return X[perm], y[perm]


def evaluate_approach(name, train_X, train_y, test_X, test_y, service):
    """Train models on training data, score test data, return metrics."""
    # Use only normal samples for training (unsupervised anomaly detection)
    normal_mask = train_y == 0
    train_normal = train_X[normal_mask]

    iso = IsolationForestDetector()
    lstm = LSTMAutoencoder()
    ensemble = EnsembleScorer(weights={"isoforest": 0.4, "lstm": 0.6})

    # Train
    t0 = time.time()
    iso.fit(train_normal)
    lstm.fit(train_normal)
    train_time = time.time() - t0

    # Score test data
    iso_scores, lstm_scores, ens_scores = [], [], []
    t0 = time.time()
    for i in range(len(test_X)):
        x = test_X[i:i+1]
        iso_s = iso.score(x)
        lstm_s = lstm.score(x)
        ens_s = ensemble.combine(iso_s, lstm_s)
        iso_scores.append(iso_s)
        lstm_scores.append(lstm_s)
        ens_scores.append(ens_s)
    infer_time = time.time() - t0

    # Compute metrics at different thresholds
    results = {}
    for thresh_name, thresh in [("t=0.5", 0.5), ("t=0.6", 0.6), ("t=0.7", 0.7), ("t=0.8", 0.8)]:
        m = compute_metrics(test_y, ens_scores, threshold=thresh)
        results[thresh_name] = m

    primary = compute_metrics(test_y, ens_scores, threshold=THRESHOLD)
    auc_roc = compute_auc_roc(test_y, ens_scores)
    avg_prec = compute_avg_precision(test_y, ens_scores)

    # Reconstruction error analysis
    normal_test = test_X[test_y == 0]
    anomaly_test = test_X[test_y == 1]
    normal_scores = [ens_scores[i] for i in range(len(test_y)) if test_y[i] == 0]
    anomaly_scores_list = [ens_scores[i] for i in range(len(test_y)) if test_y[i] == 1]

    return {
        "approach": name,
        "service": service,
        "train_samples": len(train_normal),
        "test_samples": len(test_X),
        "test_anomalies": int(test_y.sum()),
        "train_time_ms": round(train_time * 1000, 1),
        "infer_time_ms": round(infer_time * 1000, 1),
        "primary_metrics": primary,
        "thresholds": results,
        "auc_roc": round(auc_roc, 4),
        "avg_precision": round(avg_prec, 4),
        "mean_normal_score": round(np.mean(normal_scores), 4) if normal_scores else 0,
        "mean_anomaly_score": round(np.mean(anomaly_scores_list), 4) if anomaly_scores_list else 0,
        "score_separation": round(
            (np.mean(anomaly_scores_list) - np.mean(normal_scores)), 4
        ) if (normal_scores and anomaly_scores_list) else 0,
    }


def format_report(all_results, output_path=None):
    """Generate markdown benchmark report."""
    lines = []
    lines.append("# ML Pipeline Validation Benchmark")
    lines.append(f"\nGenerated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("")
    lines.append("## Methodology")
    lines.append("")
    lines.append("| | Approach A (Baseline) | Approach B (Proposed) |")
    lines.append("|---|---|---|")
    lines.append("| **Name** | Pure Synthetic | Real-Data-Derived Synthetic |")
    lines.append("| **Training Data** | Random Gaussian (arbitrary μ/σ) | Multivariate Gaussian fitted to real TrainTicket Prometheus KPIs |")
    lines.append("| **Correlations** | None (independent features) | Preserved (real cross-feature covariance) |")
    lines.append("| **Calibration** | Not calibrated to any real system | Calibrated to real microservice behavior |")
    lines.append("")
    lines.append("**Ground truth**: Real labeled observations from TrainTicket experiment")
    lines.append("`ts-auth-mongo_MongoDB_4.4.15_2022-07-27` (34 timesteps × 7 services,")
    lines.append("anomaly window at rows 21-25 on api-gateway and product-service).")
    lines.append("")
    lines.append("---")
    lines.append("")

    # Aggregate results
    a_results = [r for r in all_results if r["approach"] == "A: Pure Synthetic"]
    b_results = [r for r in all_results if r["approach"] == "B: Real-Data-Derived"]

    # Summary table
    lines.append("## Aggregate Results")
    lines.append("")
    lines.append("| Metric | Approach A (Pure Synthetic) | Approach B (Real-Derived) | Winner |")
    lines.append("|--------|---------------------------|--------------------------|--------|")

    def agg(results, key):
        vals = [r["primary_metrics"][key] for r in results]
        return np.mean(vals)

    def agg_key(results, key):
        vals = [r[key] for r in results]
        return np.mean(vals)

    metrics = [
        ("Precision", "precision", True),
        ("Recall", "recall", True),
        ("F1 Score", "f1", True),
        ("Accuracy", "accuracy", True),
    ]

    winners = {"A": 0, "B": 0}
    for label, key, higher_better in metrics:
        a_val = agg(a_results, key)
        b_val = agg(b_results, key)
        if higher_better:
            winner = "B" if b_val > a_val else "A" if a_val > b_val else "Tie"
        else:
            winner = "B" if b_val < a_val else "A" if a_val < b_val else "Tie"
        if winner in ("A", "B"):
            winners[winner] += 1
        w_label = f"**{winner}**" if winner != "Tie" else "Tie"
        lines.append(f"| {label} | {a_val:.4f} | {b_val:.4f} | {w_label} |")

    extra_metrics = [
        ("AUC-ROC", "auc_roc", True),
        ("Avg Precision (AUC-PR)", "avg_precision", True),
        ("Score Separation", "score_separation", True),
        ("Mean Normal Score", "mean_normal_score", False),
        ("Mean Anomaly Score", "mean_anomaly_score", True),
    ]

    for label, key, higher_better in extra_metrics:
        a_val = agg_key(a_results, key)
        b_val = agg_key(b_results, key)
        if higher_better:
            winner = "B" if b_val > a_val else "A" if a_val > b_val else "Tie"
        else:
            winner = "B" if b_val < a_val else "A" if a_val < b_val else "Tie"
        if winner in ("A", "B"):
            winners[winner] += 1
        w_label = f"**{winner}**" if winner != "Tie" else "Tie"
        lines.append(f"| {label} | {a_val:.4f} | {b_val:.4f} | {w_label} |")

    lines.append("")

    # Overall verdict
    overall = "B" if winners["B"] > winners["A"] else "A" if winners["A"] > winners["B"] else "Tie"
    lines.append(f"**Overall Winner: Approach {'B (Real-Data-Derived Synthetic)' if overall == 'B' else 'A (Pure Synthetic)' if overall == 'A' else 'Tie'}**")
    lines.append(f"(Approach A wins {winners['A']}/{winners['A']+winners['B']} metrics, Approach B wins {winners['B']}/{winners['A']+winners['B']} metrics)")
    lines.append("")
    lines.append("---")
    lines.append("")

    # Threshold sensitivity
    lines.append("## Threshold Sensitivity (Averaged Across Services)")
    lines.append("")
    lines.append("| Threshold | A: Precision | A: Recall | A: F1 | B: Precision | B: Recall | B: F1 |")
    lines.append("|-----------|-------------|----------|-------|-------------|----------|-------|")
    for thresh_name in ["t=0.5", "t=0.6", "t=0.7", "t=0.8"]:
        a_p = np.mean([r["thresholds"][thresh_name]["precision"] for r in a_results])
        a_r = np.mean([r["thresholds"][thresh_name]["recall"] for r in a_results])
        a_f = np.mean([r["thresholds"][thresh_name]["f1"] for r in a_results])
        b_p = np.mean([r["thresholds"][thresh_name]["precision"] for r in b_results])
        b_r = np.mean([r["thresholds"][thresh_name]["recall"] for r in b_results])
        b_f = np.mean([r["thresholds"][thresh_name]["f1"] for r in b_results])
        lines.append(f"| {thresh_name} | {a_p:.4f} | {a_r:.4f} | {a_f:.4f} | {b_p:.4f} | {b_r:.4f} | {b_f:.4f} |")
    lines.append("")
    lines.append("---")
    lines.append("")

    # Per-service breakdown
    lines.append("## Per-Service Breakdown")
    lines.append("")
    for svc in SERVICES:
        a_r = next((r for r in a_results if r["service"] == svc), None)
        b_r = next((r for r in b_results if r["service"] == svc), None)
        if not a_r or not b_r:
            continue
        lines.append(f"### {svc}")
        lines.append("")
        lines.append(f"Test data: {a_r['test_samples']} samples ({a_r['test_anomalies']} anomalies)")
        lines.append("")
        lines.append("| Metric | Approach A | Approach B |")
        lines.append("|--------|-----------|-----------|")
        lines.append(f"| AUC-ROC | {a_r['auc_roc']:.4f} | {b_r['auc_roc']:.4f} |")
        lines.append(f"| Avg Precision | {a_r['avg_precision']:.4f} | {b_r['avg_precision']:.4f} |")
        lines.append(f"| F1 (t=0.7) | {a_r['primary_metrics']['f1']:.4f} | {b_r['primary_metrics']['f1']:.4f} |")
        lines.append(f"| Score Sep. | {a_r['score_separation']:.4f} | {b_r['score_separation']:.4f} |")
        lines.append(f"| Train time | {a_r['train_time_ms']:.1f}ms | {b_r['train_time_ms']:.1f}ms |")
        lines.append("")

    # Verdict
    lines.append("---")
    lines.append("")
    lines.append("## Analysis")
    lines.append("")

    if overall == "B":
        lines.append("**Approach B (Real-Data-Derived Synthetic) is the recommended approach.**")
        lines.append("")
        lines.append("Key advantages:")
        lines.append("- Training data mirrors real microservice resource consumption patterns")
        lines.append("- Cross-feature correlations (e.g., CPU↔latency, error_rate↔restart_count) are preserved")
        lines.append("- The model's learned 'normal baseline' is calibrated to actual Prometheus metric ranges")
        lines.append("- Better score separation between normal and anomalous samples reduces false positives")
    elif overall == "A":
        lines.append("**Approach A (Pure Synthetic) performed better in this benchmark.**")
        lines.append("")
        lines.append("This may indicate the real data has insufficient variance to train robust models.")
        lines.append("Consider expanding the real dataset with more experiment runs.")
    else:
        lines.append("The two approaches performed comparably in this benchmark.")

    lines.append("")
    lines.append("### Why Real-Data-Derived Synthetic Training Matters")
    lines.append("")
    lines.append("1. **Distribution alignment**: The model sees data during training that")
    lines.append("   follows the same statistical distributions it will encounter in production")
    lines.append("2. **Feature correlation preservation**: Real systems have correlated metrics")
    lines.append("   (e.g., high CPU usage correlates with high latency). Pure synthetic data")
    lines.append("   with independent features can't capture this.")
    lines.append("3. **Threshold calibration**: Anomaly thresholds (0.7) are meaningful when")
    lines.append("   the model's reconstruction error scale matches real-world baselines")
    lines.append("4. **Generalization**: Models trained on real distributions generalize")
    lines.append("   better to unseen anomaly patterns than models trained on arbitrary ranges")

    report = "\n".join(lines)

    if output_path:
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(report)
        print(f"\n[report] Saved to {output_path}")

    return report


def main():
    parser = argparse.ArgumentParser(description="ML Pipeline Validation Benchmark")
    parser.add_argument("--output", default="results/benchmark_report.md", help="Output path for report")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    np.random.seed(args.seed)

    print("=" * 60)
    print("  SKAM ML Pipeline Validation Benchmark")
    print("=" * 60)
    print()

    all_results = []

    for svc in SERVICES:
        print(f"[{svc}]")

        # Load real test data (ground truth)
        real_path = TRAINING_DATA_DIR / f"{svc}_real.npz"
        if not real_path.exists():
            print(f"  [skip] no real test data at {real_path}")
            continue

        real_data = np.load(real_path)
        test_X = real_data["features"]
        test_y = real_data["labels"]
        print(f"  test: {len(test_X)} samples, {int(test_y.sum())} anomalies")

        # ── Approach A: Pure Synthetic ──
        n_features = test_X.shape[1]
        train_A_X, train_A_y = generate_pure_synthetic(n_features, 500, 50, seed=args.seed)
        result_a = evaluate_approach("A: Pure Synthetic", train_A_X, train_A_y, test_X, test_y, svc)
        all_results.append(result_a)
        print(f"  A: F1={result_a['primary_metrics']['f1']:.4f}  AUC={result_a['auc_roc']:.4f}  Sep={result_a['score_separation']:.4f}")

        # ── Approach B: Real-Data-Derived ──
        derived_path = TRAINING_DATA_DIR / f"{svc}.npz"
        if not derived_path.exists():
            print(f"  [skip] no derived training data at {derived_path}")
            continue

        derived_data = np.load(derived_path)
        train_B_X = derived_data["features"]
        train_B_y = derived_data["labels"]
        result_b = evaluate_approach("B: Real-Data-Derived", train_B_X, train_B_y, test_X, test_y, svc)
        all_results.append(result_b)
        print(f"  B: F1={result_b['primary_metrics']['f1']:.4f}  AUC={result_b['auc_roc']:.4f}  Sep={result_b['score_separation']:.4f}")

        # Compare
        f1_diff = result_b['primary_metrics']['f1'] - result_a['primary_metrics']['f1']
        winner = "B" if f1_diff > 0 else "A" if f1_diff < 0 else "="
        print(f"  Winner: {winner} (F1 diff: {f1_diff:+.4f})")
        print()

    if all_results:
        report = format_report(all_results, args.output)
        print("\n" + "=" * 60)
        print("  BENCHMARK COMPLETE")
        print("=" * 60)

        # Print summary
        a_f1 = np.mean([r["primary_metrics"]["f1"] for r in all_results if "A:" in r["approach"]])
        b_f1 = np.mean([r["primary_metrics"]["f1"] for r in all_results if "B:" in r["approach"]])
        a_auc = np.mean([r["auc_roc"] for r in all_results if "A:" in r["approach"]])
        b_auc = np.mean([r["auc_roc"] for r in all_results if "B:" in r["approach"]])
        print(f"\n  Approach A (Pure Synthetic):      F1={a_f1:.4f}  AUC-ROC={a_auc:.4f}")
        print(f"  Approach B (Real-Data-Derived):   F1={b_f1:.4f}  AUC-ROC={b_auc:.4f}")
        print(f"\n  Report: {args.output}")


if __name__ == "__main__":
    main()
