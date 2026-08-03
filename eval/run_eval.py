"""
Evaluation harness for the fraud scanner.

Answers the question a demo cannot: how well does the detector actually work?

Reports, for the document detector and the phishing detector separately:

  * a confusion matrix and precision / recall / F1 at the production threshold
  * a threshold sweep, so the precision-recall tradeoff is visible instead of
    assumed
  * per-signal analysis: how often each individual check fires on fraudulent
    vs. legitimate documents, which shows which heuristics are doing real work
    and which are mostly noise
  * every individual miss, named, so failures are documented rather than hidden

Run:
    python eval/run_eval.py                # human-readable report
    python eval/run_eval.py --json         # machine-readable, for CI
    python eval/run_eval.py --markdown     # writes eval/RESULTS.md

Exits non-zero if F1 falls below --min-f1, so CI can catch a regression in
detection quality the same way it catches a failing unit test.
"""

import argparse
import json
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import app  # noqa: E402
from dataset import CASES, EMAIL_CASES  # noqa: E402

# The production app calls anything >= 50 "HIGH" and >= 20 "MEDIUM".
# We treat MEDIUM-and-above as "flagged for human review", since that is what
# the tool actually asks a user to act on.
DEFAULT_THRESHOLD = 20


# ----------------------------------------------------------------------
# Metrics
# ----------------------------------------------------------------------

def confusion(predictions):
    """predictions: list of (predicted_positive: bool, actual_positive: bool)"""
    tp = sum(1 for p, a in predictions if p and a)
    fp = sum(1 for p, a in predictions if p and not a)
    fn = sum(1 for p, a in predictions if not p and a)
    tn = sum(1 for p, a in predictions if not p and not a)
    return tp, fp, fn, tn


def metrics(tp, fp, fn, tn):
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
    total = tp + fp + fn + tn
    accuracy = (tp + tn) / total if total else 0.0
    return {
        "precision": round(precision, 3),
        "recall": round(recall, 3),
        "f1": round(f1, 3),
        "accuracy": round(accuracy, 3),
        "tp": tp, "fp": fp, "fn": fn, "tn": tn,
    }


# ----------------------------------------------------------------------
# Scoring the datasets
# ----------------------------------------------------------------------

def score_documents():
    """Run every document case through evaluate(). Returns list of results."""
    results = []
    for c in CASES:
        findings, score = app.evaluate(
            c["text"], c["metadata"],
            approved_vendors=c["vendors"],
            claims_to_be_original=c["claims_original"],
        )
        results.append({
            "id": c["id"],
            "label": c["label"],
            "actual_positive": c["label"] == "fraud",
            "score": score,
            "band": app.risk_band(score)[0],
            "findings": [f["title"] for f in findings],
            "difficulty": c["difficulty"],
            "note": c["note"],
        })
    return results


def score_emails():
    results = []
    for c in EMAIL_CASES:
        findings, score = app.check_email(c["text"], c["sender"])
        results.append({
            "id": c["id"],
            "label": c["label"],
            "actual_positive": c["label"] == "phishing",
            "score": score,
            "band": app.risk_band(score)[0],
            "findings": [f["title"] for f in findings],
            "difficulty": c["difficulty"],
            "note": c["note"],
        })
    return results


def evaluate_at(results, threshold):
    preds = [(r["score"] >= threshold, r["actual_positive"]) for r in results]
    return metrics(*confusion(preds))


def threshold_sweep(results, lo=0, hi=101, step=5):
    rows = []
    for t in range(lo, hi, step):
        m = evaluate_at(results, t)
        rows.append({"threshold": t, **m})
    return rows


def best_threshold(sweep):
    return max(sweep, key=lambda r: (r["f1"], r["recall"]))


def signal_analysis(results):
    """How often does each individual check fire on fraud vs. clean?

    A check that fires equally on both is not carrying information, however
    intuitive it seems.
    """
    fires = defaultdict(lambda: {"on_fraud": 0, "on_clean": 0})
    for r in results:
        for title in r["findings"]:
            key = "on_fraud" if r["actual_positive"] else "on_clean"
            fires[title][key] += 1

    rows = []
    for title, counts in fires.items():
        total = counts["on_fraud"] + counts["on_clean"]
        rows.append({
            "signal": title,
            "on_fraud": counts["on_fraud"],
            "on_clean": counts["on_clean"],
            "precision": round(counts["on_fraud"] / total, 3) if total else 0.0,
        })
    return sorted(rows, key=lambda r: (-r["precision"], -r["on_fraud"]))


def errors(results, threshold):
    fps, fns = [], []
    for r in results:
        predicted = r["score"] >= threshold
        if predicted and not r["actual_positive"]:
            fps.append(r)
        elif not predicted and r["actual_positive"]:
            fns.append(r)
    return fps, fns


# ----------------------------------------------------------------------
# Reporting
# ----------------------------------------------------------------------

def build_report(threshold):
    docs = score_documents()
    emails = score_emails()

    doc_sweep = threshold_sweep(docs)
    email_sweep = threshold_sweep(emails)

    doc_fp, doc_fn = errors(docs, threshold)
    email_fp, email_fn = errors(emails, threshold)

    return {
        "threshold": threshold,
        "documents": {
            "n": len(docs),
            "n_fraud": sum(1 for r in docs if r["actual_positive"]),
            "n_clean": sum(1 for r in docs if not r["actual_positive"]),
            "metrics": evaluate_at(docs, threshold),
            "sweep": doc_sweep,
            "best_threshold": best_threshold(doc_sweep),
            "signals": signal_analysis(docs),
            "false_positives": [{"id": r["id"], "score": r["score"],
                                 "findings": r["findings"], "note": r["note"]}
                                for r in doc_fp],
            "false_negatives": [{"id": r["id"], "score": r["score"],
                                 "findings": r["findings"], "note": r["note"]}
                                for r in doc_fn],
            "cases": docs,
        },
        "emails": {
            "n": len(emails),
            "n_phishing": sum(1 for r in emails if r["actual_positive"]),
            "n_legitimate": sum(1 for r in emails if not r["actual_positive"]),
            "metrics": evaluate_at(emails, threshold),
            "sweep": email_sweep,
            "best_threshold": best_threshold(email_sweep),
            "signals": signal_analysis(emails),
            "false_positives": [{"id": r["id"], "score": r["score"],
                                 "findings": r["findings"], "note": r["note"]}
                                for r in email_fp],
            "false_negatives": [{"id": r["id"], "score": r["score"],
                                 "findings": r["findings"], "note": r["note"]}
                                for r in email_fn],
            "cases": emails,
        },
    }


def _fmt_metrics(m):
    return (f"precision {m['precision']:.2f}  ·  recall {m['recall']:.2f}  ·  "
            f"F1 {m['f1']:.2f}  ·  accuracy {m['accuracy']:.2f}")


def print_report(rep):
    t = rep["threshold"]
    line = "=" * 68

    for key, title, pos, neg in [
        ("documents", "DOCUMENT FRAUD DETECTION", "fraud", "clean"),
        ("emails", "PHISHING EMAIL DETECTION", "phishing", "legitimate"),
    ]:
        d = rep[key]
        m = d["metrics"]
        print(f"\n{line}\n{title}\n{line}")
        print(f"Cases: {d['n']}  ({d.get('n_fraud', d.get('n_phishing'))} {pos}, "
              f"{d.get('n_clean', d.get('n_legitimate'))} {neg})")
        print(f"Flag threshold: score >= {t}\n")

        print("Confusion matrix")
        print(f"  {'':<22}predicted {pos:<14}predicted {neg}")
        print(f"  actual {pos:<15}{m['tp']:<24}{m['fn']}")
        print(f"  actual {neg:<15}{m['fp']:<24}{m['tn']}\n")
        print(f"  {_fmt_metrics(m)}")

        bt = d["best_threshold"]
        print(f"\n  Best F1 in sweep: {bt['f1']:.2f} at threshold {bt['threshold']} "
              f"(precision {bt['precision']:.2f}, recall {bt['recall']:.2f})")

        print("\nThreshold sweep")
        print("  thresh   precision   recall     F1")
        for row in d["sweep"]:
            if row["threshold"] > 60:
                break
            print(f"  {row['threshold']:>6}   {row['precision']:>9.2f}   "
                  f"{row['recall']:>6.2f}   {row['f1']:>5.2f}")

        print("\nPer-signal analysis  (how often each check fires)")
        print(f"  {'signal':<46}{pos:>7}{neg:>8}{'prec':>8}")
        for s in d["signals"]:
            print(f"  {s['signal'][:44]:<46}{s['on_fraud']:>7}"
                  f"{s['on_clean']:>8}{s['precision']:>8.2f}")

        if d["false_positives"]:
            print(f"\nFalse positives  ({len(d['false_positives'])})")
            for e in d["false_positives"]:
                print(f"  · {e['id']}  (score {e['score']})")
                print(f"      fired: {', '.join(e['findings']) or 'none'}")
                print(f"      {e['note']}")
        else:
            print("\nFalse positives: none")

        if d["false_negatives"]:
            print(f"\nFalse negatives  ({len(d['false_negatives'])})")
            for e in d["false_negatives"]:
                print(f"  · {e['id']}  (score {e['score']})")
                print(f"      fired: {', '.join(e['findings']) or 'none'}")
                print(f"      {e['note']}")
        else:
            print("\nFalse negatives: none")

    print(f"\n{line}\n")


def markdown_report(rep):
    t = rep["threshold"]
    out = ["# Detection quality report",
           "",
           "Generated by `eval/run_eval.py`. Measures the detection logic "
           "against a labeled dataset rather than relying on spot checks.",
           "",
           f"**Flag threshold:** a document is treated as flagged when its risk "
           f"score is **>= {t}** (the app's MEDIUM band and above).",
           ""]

    for key, title, pos, neg in [
        ("documents", "Document fraud detection", "fraud", "clean"),
        ("emails", "Phishing email detection", "phishing", "legitimate"),
    ]:
        d = rep[key]
        m = d["metrics"]
        npos = d.get("n_fraud", d.get("n_phishing"))
        nneg = d.get("n_clean", d.get("n_legitimate"))

        out += [f"## {title}", "",
                f"{d['n']} labeled cases ({npos} {pos}, {nneg} {neg}).", "",
                "| | predicted " + pos + " | predicted " + neg + " |",
                "|---|---|---|",
                f"| **actual {pos}** | {m['tp']} | {m['fn']} |",
                f"| **actual {neg}** | {m['fp']} | {m['tn']} |",
                "",
                f"**Precision {m['precision']:.2f} · Recall {m['recall']:.2f} · "
                f"F1 {m['f1']:.2f} · Accuracy {m['accuracy']:.2f}**",
                ""]

        out += ["### Threshold sweep", "",
                "| threshold | precision | recall | F1 |", "|---|---|---|---|"]
        for row in d["sweep"]:
            if row["threshold"] > 60:
                break
            out.append(f"| {row['threshold']} | {row['precision']:.2f} | "
                       f"{row['recall']:.2f} | {row['f1']:.2f} |")
        bt = d["best_threshold"]
        out += ["", f"Best F1 is {bt['f1']:.2f} at threshold {bt['threshold']}.", ""]

        out += ["### Per-signal analysis", "",
                "How often each individual check fires. A signal that fires as "
                "often on legitimate documents as on fraudulent ones is not "
                "carrying information.", "",
                f"| signal | on {pos} | on {neg} | precision |",
                "|---|---|---|---|"]
        for s in d["signals"]:
            out.append(f"| {s['signal']} | {s['on_fraud']} | {s['on_clean']} | "
                       f"{s['precision']:.2f} |")
        out.append("")

        for label, items in [("False positives", d["false_positives"]),
                             ("False negatives", d["false_negatives"])]:
            out += [f"### {label}", ""]
            if not items:
                out += ["None.", ""]
            else:
                for e in items:
                    out += [f"- **{e['id']}** (score {e['score']}) — "
                            f"fired: {', '.join(e['findings']) or 'nothing'}. "
                            f"{e['note']}"]
                out.append("")

    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--threshold", type=int, default=DEFAULT_THRESHOLD)
    ap.add_argument("--json", action="store_true", help="print JSON instead")
    ap.add_argument("--markdown", action="store_true",
                    help="write eval/RESULTS.md")
    ap.add_argument("--min-f1", type=float, default=0.0,
                    help="exit non-zero if document F1 falls below this")
    args = ap.parse_args()

    rep = build_report(args.threshold)

    if args.json:
        print(json.dumps(rep, indent=2, default=str))
    else:
        print_report(rep)

    if args.markdown:
        path = os.path.join(os.path.dirname(__file__), "RESULTS.md")
        with open(path, "w") as fh:
            fh.write(markdown_report(rep))
        print(f"Wrote {path}")

    f1 = rep["documents"]["metrics"]["f1"]
    if f1 < args.min_f1:
        print(f"\nFAIL: document F1 {f1:.2f} is below the required "
              f"{args.min_f1:.2f}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
