from __future__ import annotations

import json
import random
from pathlib import Path

from db import conn

BASE = Path(__file__).parent
CONTENT_PATH = BASE / "content" / "quant-module-01-gold.json"


def _pct(x: float) -> str:
    return f"{x * 100:.2f}%"


def _number_options(correct: float, seed: int, spread: float = 0.025):
    rng = random.Random(seed)
    vals = [correct]
    for mult in (-2, -1, 1, 2, 3):
        candidate = correct + mult * spread
        if all(abs(candidate - v) > 1e-8 for v in vals):
            vals.append(candidate)
        if len(vals) >= 3:
            break
    rng.shuffle(vals)
    vals = vals[:3]
    return [_pct(v) for v in vals], "ABC"[vals.index(correct)]


def _money_options(correct: float, seed: int, spread: float = 4.0):
    rng = random.Random(seed)
    vals = [round(correct, 2)]
    for mult in (-2, -1, 1, 2, 3):
        candidate = round(correct + mult * spread, 2)
        if candidate > 0 and candidate not in vals:
            vals.append(candidate)
        if len(vals) >= 3:
            break
    rng.shuffle(vals)
    vals = vals[:3]
    return [f"{v:.2f}" for v in vals], "ABC"[vals.index(round(correct, 2))]


def _mcq(prompt, options, correct, explanation, concept, difficulty=2, qtype="calculation", source_ref=None):
    return {
        "prompt": prompt, "options": options, "correct": correct,
        "explanation": explanation, "concept": concept,
        "difficulty": difficulty, "type": qtype, "sourceRef": source_ref,
    }


def generate_questions():
    """Generate deterministic, original practice variants for Module 1."""
    qs = []

    for i in range(16):
        p0 = 80 + 5 * i
        p1 = p0 + (-6 + (i % 9) * 2)
        d = 1 + (i % 4) * 0.75
        r = (p1 - p0 + d) / p0
        options, key = _number_options(r, 100 + i, max(0.01, abs(r) * 0.35 + 0.008))
        qs.append(_mcq(
            f"An asset is purchased for {p0:.2f}, ends the period at {p1:.2f}, and pays a cash distribution of {d:.2f}. What is the holding-period return?",
            options, key,
            f"Use (P1 − P0 + D) / P0 = ({p1:.2f} − {p0:.2f} + {d:.2f}) / {p0:.2f} = {_pct(r)}.",
            "m1-holding-period-return", 1 if i < 5 else 2, source_ref=f"original:m1:hpr:{i+1}"
        ))

    for i in range(10):
        p0 = 95 + 7 * i
        p1 = p0 * (1 + (-0.08 + 0.025 * (i % 8)))
        r = (p1 - p0) / p0
        options, key = _number_options(r, 200 + i, 0.02)
        qs.append(_mcq(
            f"A security's price moves from {p0:.2f} to {p1:.2f}. Ignoring any cash distributions, what is the price return?",
            options, key,
            f"Price return = (P1 − P0) / P0 = ({p1:.2f} − {p0:.2f}) / {p0:.2f} = {_pct(r)}.",
            "m1-price-return", 1, source_ref=f"original:m1:price:{i+1}"
        ))

    for i in range(10):
        p0 = 50 + 10 * i
        d = 1 + 0.5 * (i % 6)
        r = d / p0
        options, key = _number_options(r, 300 + i, 0.01)
        qs.append(_mcq(
            f"An asset begins the period at {p0:.2f} and pays cash income of {d:.2f}. What is its income yield for the period?",
            options, key,
            f"Income yield = D / P0 = {d:.2f} / {p0:.2f} = {_pct(r)}.",
            "m1-income-yield", 1, source_ref=f"original:m1:income:{i+1}"
        ))

    for i in range(12):
        price_r = -0.06 + 0.015 * (i % 9)
        income_r = 0.01 + 0.004 * (i % 5)
        total = price_r + income_r
        options, key = _number_options(total, 400 + i, 0.015)
        qs.append(_mcq(
            f"An asset has a price return of {_pct(price_r)} and an income yield of {_pct(income_r)} over the same holding period. What is its total return?",
            options, key,
            f"With a common beginning-value denominator, total return = price return + income yield = {_pct(total)}.",
            "m1-return-decomposition", 1 if i < 4 else 2, source_ref=f"original:m1:decomp:{i+1}"
        ))

    for i in range(8):
        r = -0.35 + 0.1 * i
        wr = 1 + r
        options = [f"{wr:.2f}", f"{r:.2f}", f"{1-r:.2f}"]
        rng = random.Random(500+i); rng.shuffle(options)
        qs.append(_mcq(
            f"A period return is {_pct(r)}. What is the corresponding wealth relative?",
            options, "ABC"[options.index(f"{wr:.2f}")],
            f"Wealth relative = 1 + R = {wr:.2f}.",
            "m1-wealth-relative", 1, "concept", f"original:m1:wealth:{i+1}"
        ))
    for i, loss in enumerate((0.10, 0.20, 0.25, 0.40), 1):
        recovery = 1/(1-loss)-1
        options, key = _number_options(recovery, 550+i, 0.05)
        qs.append(_mcq(
            f"A portfolio loses {_pct(-loss)}. What subsequent positive return is required to return exactly to its original value?",
            options, key,
            f"After the loss, wealth is {1-loss:.2f}. Solve (1−loss)(1+g)=1, so g = 1/(1−loss)−1 = {_pct(recovery)}.",
            "m1-wealth-relative", 2, source_ref=f"original:m1:recovery:{i}"
        ))

    for i in range(16):
        r1 = -0.12 + 0.03 * (i % 8)
        r2 = -0.08 + 0.025 * ((i * 3) % 7)
        cum = (1+r1)*(1+r2)-1
        options, key = _number_options(cum, 600+i, 0.025)
        qs.append(_mcq(
            f"An investment earns {_pct(r1)} in period 1 and {_pct(r2)} in period 2. What is the cumulative return across both periods?",
            options, key,
            f"Cumulative return = (1+R1)(1+R2)−1 = ({1+r1:.4f})({1+r2:.4f})−1 = {_pct(cum)}.",
            "m1-cumulative-return", 2, source_ref=f"original:m1:cumulative:{i+1}"
        ))

    for i in range(12):
        years = 2 + (i % 4)
        annual = 0.03 + 0.015 * (i % 7)
        cumulative = (1+annual)**years - 1
        options, key = _number_options(annual, 700+i, 0.015)
        qs.append(_mcq(
            f"An investment has a cumulative return of {_pct(cumulative)} over {years} years. What constant annual compound return produces the same terminal wealth?",
            options, key,
            f"Annualized return = (1+R_cum)^(1/n)−1 = ({1+cumulative:.6f})^(1/{years})−1 = {_pct(annual)}.",
            "m1-annualized-return", 2 if years <= 3 else 3, source_ref=f"original:m1:annualized:{i+1}"
        ))

    for i in range(8):
        p0 = 100 + 10 * i
        r = 0.04 + 0.015 * (i % 5)
        d = 1.5 + 0.5 * (i % 4)
        p1 = p0*(1+r)-d
        options, key = _money_options(p1, 800+i, max(2.0, p0*0.025))
        qs.append(_mcq(
            f"An asset begins at {p0:.2f}. An investor requires a holding-period return of {_pct(r)} and expects a cash distribution of {d:.2f}. What ending price is required?",
            options, key,
            f"Rearrange R=(P1−P0+D)/P0: P1=P0(1+R)−D={p0:.2f}×{1+r:.4f}−{d:.2f}={p1:.2f}.",
            "m1-reverse-return", 2, source_ref=f"original:m1:reverse:{i+1}"
        ))

    return qs


def seed_module1():
    content = json.loads(CONTENT_PATH.read_text(encoding="utf-8"))
    c = conn(); cur = c.cursor()
    tid = cur.execute("SELECT id FROM topics WHERE slug=?", (content["topicSlug"],)).fetchone()[0]
    cur.execute(
        """INSERT INTO learning_modules(topic_id,slug,name,sort_order,source_module_id)
           VALUES(?,?,?,?,?) ON CONFLICT(slug) DO UPDATE SET topic_id=excluded.topic_id,name=excluded.name,sort_order=excluded.sort_order""",
        (tid, content["slug"], content["title"], content["moduleNumber"], "quant-module-01")
    )
    module_id = cur.execute("SELECT id FROM learning_modules WHERE slug=?", (content["slug"],)).fetchone()[0]

    for cp in content["concepts"]:
        cur.execute(
            """INSERT INTO concepts(topic_id,module_id,slug,name,description,importance,prerequisite_slugs)
               VALUES(?,?,?,?,?,?,?) ON CONFLICT(slug) DO UPDATE SET topic_id=excluded.topic_id,module_id=excluded.module_id,name=excluded.name,description=excluded.description,importance=excluded.importance,prerequisite_slugs=excluded.prerequisite_slugs""",
            (tid, module_id, cp["slug"], cp["name"], cp["summary"], cp["importance"], json.dumps(cp.get("prerequisites", [])))
        )

    for cp in content["concepts"]:
        cid = cur.execute("SELECT id FROM concepts WHERE slug=?", (cp["slug"],)).fetchone()[0]
        for prereq_slug in cp.get("prerequisites", []):
            row = cur.execute("SELECT id FROM concepts WHERE slug=?", (prereq_slug,)).fetchone()
            if row:
                cur.execute("INSERT OR IGNORE INTO concept_prerequisites(concept_id,prerequisite_concept_id) VALUES(?,?)", (cid, row[0]))

    for f in content["formulas"]:
        cid = cur.execute("SELECT id FROM concepts WHERE slug=?", (f["concept"],)).fetchone()[0]
        cur.execute(
            """INSERT OR IGNORE INTO formulas(concept_id,name,expression,variables_json,explanation,source_ref)
               VALUES(?,?,?,?,?,?)""",
            (cid, f["name"], f["expression"], json.dumps(f.get("variables", {}), ensure_ascii=False), f.get("explanation"), "original:module1")
        )

    questions = generate_questions()
    for q in questions:
        cp_id = cur.execute("SELECT id FROM concepts WHERE slug=?", (q["concept"],)).fetchone()[0]
        opts = q["options"] + [None] * (4-len(q["options"]))
        cur.execute(
            """INSERT OR IGNORE INTO questions(topic_id,module_id,prompt,option_a,option_b,option_c,option_d,correct,explanation,difficulty,question_type,source_ref,content_version,active)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,1)""",
            (tid,module_id,q["prompt"],opts[0],opts[1],opts[2],opts[3],q["correct"],q["explanation"],q["difficulty"],q["type"],q["sourceRef"],"original-module1-v1")
        )
        qid = cur.execute("SELECT id FROM questions WHERE prompt=?", (q["prompt"],)).fetchone()[0]
        cur.execute("UPDATE questions SET module_id=?,source_ref=?,content_version='original-module1-v1',active=1 WHERE id=?", (module_id,q["sourceRef"],qid))
        cur.execute("INSERT OR IGNORE INTO question_concepts(question_id,concept_id,weight) VALUES(?,?,1.0)", (qid, cp_id))

    c.commit(); c.close()
    return {"module": content["slug"], "questions": len(questions), "concepts": len(content["concepts"]), "formulas": len(content["formulas"])}
