from __future__ import annotations

import math
import random
from collections import defaultdict
from datetime import datetime, timedelta, timezone

UTC = timezone.utc

MIX = {
    "due": 0.35,
    "errors": 0.25,
    "weak": 0.25,
    "new": 0.15,
}

SELF_ASSESSMENT_WEIGHT = {
    "knew": 1.0,
    "guessed": 0.45,
    "didnt_know": 0.15,
}


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def clamp(v, lo, hi):
    return max(lo, min(hi, v))


def update_srs(ease: float, interval: int, reps: int, correct: bool, self_assessment: str):
    """SM-2 inspired scheduling with a strong penalty for lucky guesses."""
    assessment = SELF_ASSESSMENT_WEIGHT.get(self_assessment, 0.45)
    if not correct:
        quality = 1 if self_assessment == "knew" else 0
    elif self_assessment == "knew":
        quality = 5
    elif self_assessment == "guessed":
        quality = 3
    else:
        quality = 2

    if quality < 3:
        reps = 0
        interval = 1
    else:
        if self_assessment == "guessed":
            interval = 1 if reps == 0 else min(3, max(1, interval))
            reps = max(1, reps)
        else:
            interval = 1 if reps == 0 else 4 if reps == 1 else max(1, round(interval * ease))
            reps += 1

    ease = clamp(ease + (0.1 - (5 - quality) * (0.08 + (5 - quality) * 0.02)), 1.3, 3.0)
    if correct and self_assessment == "guessed":
        ease = max(1.3, ease - 0.12)
    if correct and self_assessment == "didnt_know":
        interval = 1
    due = datetime.now(UTC) + timedelta(days=interval)
    return ease, interval, reps, due.isoformat()


def evidence_weight(correct: bool, self_assessment: str, difficulty: int, duration_ms: int | None = None) -> tuple[float, float]:
    """Return positive/negative Bayesian evidence for a concept mastery Beta posterior."""
    base = SELF_ASSESSMENT_WEIGHT.get(self_assessment, 0.45)
    difficulty_factor = {1: 0.85, 2: 1.0, 3: 1.2}.get(int(difficulty or 2), 1.0)
    speed_factor = 1.0
    if duration_ms and duration_ms > 0:
        seconds = duration_ms / 1000
        if seconds < 20:
            speed_factor = 1.06
        elif seconds > 120:
            speed_factor = 0.85
    evidence = clamp(base * difficulty_factor * speed_factor, 0.08, 1.35)
    if correct:
        return evidence, 0.0
    return 0.0, max(0.55, difficulty_factor) * (1.15 if self_assessment == "knew" else 1.0)


def mastery_probability(alpha: float, beta: float) -> float:
    return clamp(float(alpha) / max(0.001, float(alpha) + float(beta)), 0.0, 1.0)


def confidence_band(probability: float, exposures: int) -> str:
    if exposures < 2:
        return "unseen"
    if probability >= 0.85:
        return "mastered"
    if probability >= 0.70:
        return "strong"
    if probability >= 0.50:
        return "developing"
    return "weak"


def days_until(exam_date: str | None) -> int | None:
    if not exam_date:
        return None
    try:
        d = datetime.fromisoformat(exam_date).date()
    except ValueError:
        return None
    return (d - datetime.now(UTC).date()).days


def recommended_daily_questions(exam_date: str | None, base_target: int = 30) -> int:
    days = days_until(exam_date)
    if days is None:
        return base_target
    if days <= 7:
        return max(base_target, 70)
    if days <= 21:
        return max(base_target, 55)
    if days <= 45:
        return max(base_target, 45)
    if days <= 90:
        return max(base_target, 35)
    return base_target


def readiness_score(concepts: list[dict], accuracy30: float, coverage: float, recent_speed_s: float | None = None) -> int:
    if concepts:
        weighted = []
        for c in concepts:
            p = float(c.get("probability", 0.25))
            importance = float(c.get("importance", 1.0))
            weighted.append((p, importance))
        mastery = sum(p * w for p, w in weighted) / max(0.001, sum(w for _, w in weighted))
    else:
        mastery = 0.0
    speed = 1.0 if recent_speed_s is None else clamp(90 / max(45, recent_speed_s), 0.65, 1.05)
    score = 100 * (0.52 * mastery + 0.28 * (accuracy30 / 100) + 0.20 * coverage) * speed
    return round(clamp(score, 0, 100))


def allocate_mix(total: int, mix: dict[str, float] | None = None) -> dict[str, int]:
    mix = mix or MIX
    raw = {k: total * v for k, v in mix.items()}
    out = {k: int(v) for k, v in raw.items()}
    remainder = total - sum(out.values())
    for k, _ in sorted(raw.items(), key=lambda x: x[1] - int(x[1]), reverse=True)[:remainder]:
        out[k] += 1
    return out


def weighted_sample_without_replacement(items: list[dict], n: int, weight_key: str = "score") -> list[dict]:
    pool = list(items)
    chosen = []
    while pool and len(chosen) < n:
        weights = [max(0.001, float(x.get(weight_key, 1.0))) for x in pool]
        pick = random.choices(pool, weights=weights, k=1)[0]
        chosen.append(pick)
        pool.remove(pick)
    return chosen


def exam_topic_targets(total: int, topics: list[dict]) -> dict[int, int]:
    """Allocate exam block using midpoint of topic weight ranges, normalized to exact block size."""
    if not topics:
        return {}
    weights = {int(t["id"]): (float(t["min_weight"]) + float(t["max_weight"])) / 2 for t in topics}
    s = sum(weights.values())
    raw = {k: total * v / s for k, v in weights.items()}
    counts = {k: int(v) for k, v in raw.items()}
    remainder = total - sum(counts.values())
    order = sorted(raw, key=lambda k: raw[k] - counts[k], reverse=True)
    for k in order[:remainder]:
        counts[k] += 1
    return counts


def mistake_reason_label(reason: str | None) -> str:
    return {
        "knowledge": "Connaissance manquante",
        "formula": "Formule oubliée / mal appliquée",
        "calculation": "Erreur de calcul",
        "reading": "Question mal lue",
        "concept_confusion": "Confusion entre concepts",
        "time": "Pression / manque de temps",
        "guess": "Réponse au hasard",
        "other": "Autre",
    }.get(reason or "knowledge", "Connaissance manquante")
