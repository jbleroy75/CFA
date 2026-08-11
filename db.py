from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path(os.environ.get("DB_PATH", "/data/cfa.sqlite3"))
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

PROGRAM = {
    "slug": "cfa-program-level-i-2027",
    "name": "CFA Program – Level I 2027",
    "level": "I",
    "year": 2027,
    "source_code": "CFA-27-02-LI-B",
}

# Canonical Level I 2027 roots supplied by the user. Internal slugs stay stable so
# existing mastery/history data remains compatible across curriculum label changes.
TOPICS = [
    # slug, source label, canonical label, min/max exam weight, sort order, CFA course id, expected modules
    ("quant", "Quantitative Methods", "Quantitative Methods", 6, 9, 1, 2111, 11),
    ("economics", "Economics", "Economics", 6, 9, 2, 2112, 8),
    ("corporate", "Corporate Finance", "Corporate Issuers", 6, 9, 3, 2113, 7),
    ("fsa", "Financial Statement Analysis", "Financial Statement Analysis", 11, 14, 4, 2114, 12),
    ("equity", "Equities", "Equity Investments", 11, 14, 5, 2115, 12),
    ("fixed-income", "Fixed Income", "Fixed Income", 11, 14, 6, 2116, 19),
    ("derivatives", "Derivatives", "Derivatives", 5, 8, 7, 2117, 10),
    ("alternatives", "Alternative Investments", "Alternative Investments", 7, 10, 8, 2118, 7),
    ("portfolio", "Portfolio Construction", "Portfolio Management", 8, 12, 9, 2119, 6),
    ("ethics", "Ethical and Professional Standards", "Ethical and Professional Standards", 15, 20, 10, 2120, 10),
]

ASSESSMENT_COLLECTIONS = [
    ("mock-exams", "Mock Exams", "mock", 1),
]


# Small original demo dataset only. User-owned/licensed curriculum data is imported later.
DEMO = [
    {"topic":"quant","concept":"compound-return","concept_name":"Compound Return","prompt":"An investment grows from 100 to 121 over two years. What is its annual compound return?","options":["10%","10.5%","21%"],"correct":"A","explanation":"Because 100 × 1.10² = 121.","difficulty":1,"type":"calculation","formula":"FV = PV(1+r)^n"},
    {"topic":"quant","concept":"correlation-diversification","concept_name":"Correlation & Diversification","prompt":"If two assets have correlation +1, diversification between them can primarily:","options":["eliminate all risk","reduce risk only if weights offset exposure","create zero covariance"],"correct":"B","explanation":"Perfect positive correlation severely limits diversification; weights can still alter total volatility.","difficulty":2,"type":"concept"},
    {"topic":"economics","concept":"price-controls","concept_name":"Price Controls","prompt":"A binding price ceiling set below equilibrium price most likely creates:","options":["a surplus","a shortage","no change in quantity demanded"],"correct":"B","explanation":"A below-equilibrium ceiling raises quantity demanded and reduces quantity supplied, creating a shortage.","difficulty":1,"type":"concept"},
    {"topic":"fsa","concept":"accounting-equation","concept_name":"Accounting Equation","prompt":"Which statement best represents the accounting equation?","options":["Assets = Liabilities + Equity","Assets + Equity = Liabilities","Revenue = Assets − Liabilities"],"correct":"A","explanation":"The balance sheet identity is Assets = Liabilities + Equity.","difficulty":1,"type":"formula","formula":"Assets = Liabilities + Equity"},
    {"topic":"fsa","concept":"inventory-methods","concept_name":"Inventory Cost Methods","prompt":"All else equal, using FIFO rather than LIFO during rising prices most likely results in:","options":["higher COGS and lower inventory","lower COGS and higher inventory","identical gross profit"],"correct":"B","explanation":"FIFO assigns older, cheaper costs to COGS first, increasing ending inventory and gross profit relative to LIFO.","difficulty":2,"type":"concept"},
    {"topic":"corporate","concept":"npv-rule","concept_name":"NPV Decision Rule","prompt":"A project has positive NPV. The firm should generally:","options":["reject it because IRR is unknown","accept it because it adds value","accept it only if payback is under one year"],"correct":"B","explanation":"A positive NPV indicates expected value creation at the assumed discount rate.","difficulty":1,"type":"concept"},
    {"topic":"equity","concept":"ddm","concept_name":"Dividend Discount Model","prompt":"In a constant-growth dividend discount model, intrinsic value rises when:","options":["required return rises","growth falls","expected dividend rises"],"correct":"C","explanation":"Holding other inputs constant, a larger expected dividend increases estimated value.","difficulty":1,"type":"formula","formula":"V0 = D1 / (r-g)"},
    {"topic":"fixed-income","concept":"price-yield","concept_name":"Bond Price-Yield Relationship","prompt":"A bond's price and yield to maturity generally move:","options":["in the same direction","in opposite directions","independently"],"correct":"B","explanation":"Bond prices fall as discount rates/yields rise, and vice versa.","difficulty":1,"type":"concept"},
    {"topic":"fixed-income","concept":"duration-drivers","concept_name":"Duration Drivers","prompt":"Which bond generally has the greatest interest-rate sensitivity?","options":["Long maturity, low coupon","Short maturity, high coupon","Short maturity, floating coupon"],"correct":"A","explanation":"Longer maturity and lower coupon generally increase duration and price sensitivity.","difficulty":2,"type":"concept"},
    {"topic":"derivatives","concept":"call-payoff","concept_name":"Call Option Payoff","prompt":"At expiration, the payoff to a long call is:","options":["max(0, S−K)","max(0, K−S)","S+K"],"correct":"A","explanation":"A call gives the right to buy at K, so payoff is positive only when spot S exceeds K.","difficulty":1,"type":"formula","formula":"max(0, S-K)"},
    {"topic":"alternatives","concept":"private-equity-liquidity","concept_name":"Private Equity Liquidity","prompt":"Compared with listed equities, private equity investments are generally:","options":["more liquid","less liquid","free of valuation uncertainty"],"correct":"B","explanation":"Private equity positions are typically less liquid and valued less continuously than listed securities.","difficulty":1,"type":"concept"},
    {"topic":"portfolio","concept":"diversification","concept_name":"Diversification","prompt":"Diversification most directly reduces:","options":["systematic market risk","idiosyncratic risk","the risk-free rate"],"correct":"B","explanation":"Diversification can reduce company-specific or idiosyncratic risk.","difficulty":1,"type":"concept"},
    {"topic":"portfolio","concept":"beta","concept_name":"Beta","prompt":"Under CAPM, beta measures sensitivity to:","options":["inflation only","systematic market risk","total standalone volatility only"],"correct":"B","explanation":"Beta measures sensitivity to market movements, i.e. systematic risk.","difficulty":1,"type":"concept"},
    {"topic":"ethics","concept":"stricter-law-standard","concept_name":"Applicable Law vs Standards","prompt":"When applicable law and a professional standard differ, the prudent general approach is to follow:","options":["the stricter applicable requirement","the least strict requirement","only the employer's policy"],"correct":"A","explanation":"Where requirements conflict, the stricter applicable requirement generally governs professional conduct.","difficulty":2,"type":"concept"},
]


def conn():
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA foreign_keys=ON")
    return c


def init_db():
    c = conn(); cur = c.cursor()
    cur.executescript('''
    CREATE TABLE IF NOT EXISTS curriculum_programs(
      id INTEGER PRIMARY KEY, slug TEXT UNIQUE NOT NULL, name TEXT NOT NULL, level TEXT NOT NULL, year INTEGER NOT NULL,
      source_code TEXT, active INTEGER DEFAULT 1, created_at TEXT
    );
    CREATE TABLE IF NOT EXISTS topics(
      id INTEGER PRIMARY KEY, program_id INTEGER, slug TEXT UNIQUE, name TEXT, min_weight INTEGER, max_weight INTEGER,
      source_label TEXT, canonical_name TEXT, source_code TEXT, source_course_id INTEGER, expected_modules INTEGER DEFAULT 0, source_url TEXT,
      sort_order INTEGER DEFAULT 0, is_assessment INTEGER DEFAULT 0,
      FOREIGN KEY(program_id) REFERENCES curriculum_programs(id)
    );
    CREATE TABLE IF NOT EXISTS learning_modules(
      id INTEGER PRIMARY KEY, topic_id INTEGER NOT NULL, slug TEXT UNIQUE, name TEXT NOT NULL, sort_order INTEGER DEFAULT 0,
      source_module_id TEXT, completed INTEGER DEFAULT 0, completed_at TEXT,
      FOREIGN KEY(topic_id) REFERENCES topics(id)
    );
    CREATE TABLE IF NOT EXISTS concepts(
      id INTEGER PRIMARY KEY, topic_id INTEGER NOT NULL, module_id INTEGER, slug TEXT UNIQUE, name TEXT NOT NULL,
      los TEXT, description TEXT, importance REAL DEFAULT 1.0, prerequisite_slugs TEXT DEFAULT '[]',
      FOREIGN KEY(topic_id) REFERENCES topics(id), FOREIGN KEY(module_id) REFERENCES learning_modules(id)
    );
    CREATE TABLE IF NOT EXISTS concept_prerequisites(
      concept_id INTEGER NOT NULL, prerequisite_concept_id INTEGER NOT NULL,
      PRIMARY KEY(concept_id, prerequisite_concept_id),
      FOREIGN KEY(concept_id) REFERENCES concepts(id), FOREIGN KEY(prerequisite_concept_id) REFERENCES concepts(id)
    );
    CREATE TABLE IF NOT EXISTS formulas(
      id INTEGER PRIMARY KEY, concept_id INTEGER, name TEXT NOT NULL, expression TEXT NOT NULL, variables_json TEXT DEFAULT '{}',
      explanation TEXT, source_ref TEXT, UNIQUE(name, expression), FOREIGN KEY(concept_id) REFERENCES concepts(id)
    );
    CREATE TABLE IF NOT EXISTS questions(
      id INTEGER PRIMARY KEY, topic_id INTEGER NOT NULL, module_id INTEGER, prompt TEXT UNIQUE NOT NULL,
      option_a TEXT NOT NULL, option_b TEXT NOT NULL, option_c TEXT NOT NULL, option_d TEXT,
      correct TEXT NOT NULL, explanation TEXT NOT NULL, difficulty INTEGER DEFAULT 2,
      question_type TEXT DEFAULT 'concept', los TEXT, source_ref TEXT, content_version TEXT DEFAULT 'demo', active INTEGER DEFAULT 1,
      FOREIGN KEY(topic_id) REFERENCES topics(id), FOREIGN KEY(module_id) REFERENCES learning_modules(id)
    );
    CREATE TABLE IF NOT EXISTS question_concepts(
      question_id INTEGER NOT NULL, concept_id INTEGER NOT NULL, weight REAL DEFAULT 1.0,
      PRIMARY KEY(question_id, concept_id), FOREIGN KEY(question_id) REFERENCES questions(id), FOREIGN KEY(concept_id) REFERENCES concepts(id)
    );
    CREATE TABLE IF NOT EXISTS option_concepts(
      question_id INTEGER NOT NULL, option_key TEXT NOT NULL, concept_id INTEGER NOT NULL,
      PRIMARY KEY(question_id, option_key, concept_id),
      FOREIGN KEY(question_id) REFERENCES questions(id), FOREIGN KEY(concept_id) REFERENCES concepts(id)
    );
    CREATE TABLE IF NOT EXISTS confusions(
      correct_concept_id INTEGER NOT NULL, confused_with_concept_id INTEGER NOT NULL, count INTEGER DEFAULT 1, last_seen_at TEXT,
      PRIMARY KEY(correct_concept_id, confused_with_concept_id),
      FOREIGN KEY(correct_concept_id) REFERENCES concepts(id), FOREIGN KEY(confused_with_concept_id) REFERENCES concepts(id)
    );
    CREATE TABLE IF NOT EXISTS attempts(
      id INTEGER PRIMARY KEY, question_id INTEGER NOT NULL, session_id INTEGER, answer TEXT, correct INTEGER,
      self_assessment TEXT DEFAULT 'guessed', mistake_reason TEXT, duration_ms INTEGER, created_at TEXT,
      FOREIGN KEY(question_id) REFERENCES questions(id)
    );
    CREATE TABLE IF NOT EXISTS question_mastery(
      question_id INTEGER PRIMARY KEY, ease REAL DEFAULT 2.5, interval_days INTEGER DEFAULT 0, repetitions INTEGER DEFAULT 0,
      due_at TEXT, last_correct INTEGER, last_seen_at TEXT, FOREIGN KEY(question_id) REFERENCES questions(id)
    );
    CREATE TABLE IF NOT EXISTS concept_mastery(
      concept_id INTEGER PRIMARY KEY, alpha REAL DEFAULT 1.0, beta REAL DEFAULT 2.0, exposures INTEGER DEFAULT 0,
      correct_count INTEGER DEFAULT 0, avg_duration_ms REAL DEFAULT 0, last_seen_at TEXT,
      FOREIGN KEY(concept_id) REFERENCES concepts(id)
    );
    CREATE TABLE IF NOT EXISTS mastery_events(
      id INTEGER PRIMARY KEY, concept_id INTEGER NOT NULL, attempt_id INTEGER, probability_before REAL, probability_after REAL, created_at TEXT,
      FOREIGN KEY(concept_id) REFERENCES concepts(id)
    );
    CREATE TABLE IF NOT EXISTS error_book(
      id INTEGER PRIMARY KEY, question_id INTEGER NOT NULL, concept_id INTEGER, mistake_reason TEXT,
      times_wrong INTEGER DEFAULT 1, last_wrong_at TEXT, resolved INTEGER DEFAULT 0, note TEXT,
      UNIQUE(question_id, concept_id, mistake_reason), FOREIGN KEY(question_id) REFERENCES questions(id)
    );
    CREATE TABLE IF NOT EXISTS sessions(
      id INTEGER PRIMARY KEY, mode TEXT NOT NULL, status TEXT DEFAULT 'active', created_at TEXT, completed_at TEXT,
      target_questions INTEGER, time_limit_seconds INTEGER, exam_date_snapshot TEXT, metadata_json TEXT DEFAULT '{}'
    );
    CREATE TABLE IF NOT EXISTS session_items(
      id INTEGER PRIMARY KEY, session_id INTEGER NOT NULL, question_id INTEGER NOT NULL, position INTEGER NOT NULL,
      bucket TEXT, answered INTEGER DEFAULT 0, UNIQUE(session_id, position),
      FOREIGN KEY(session_id) REFERENCES sessions(id), FOREIGN KEY(question_id) REFERENCES questions(id)
    );
    CREATE TABLE IF NOT EXISTS assessment_collections(
      id INTEGER PRIMARY KEY, program_id INTEGER NOT NULL, slug TEXT UNIQUE NOT NULL, name TEXT NOT NULL,
      source_code TEXT, collection_type TEXT DEFAULT 'mock', sort_order INTEGER DEFAULT 0, metadata_json TEXT DEFAULT '{}', active INTEGER DEFAULT 1,
      FOREIGN KEY(program_id) REFERENCES curriculum_programs(id)
    );
    CREATE TABLE IF NOT EXISTS assessment_sets(
      id INTEGER PRIMARY KEY, program_id INTEGER NOT NULL, collection_id INTEGER, slug TEXT UNIQUE NOT NULL, name TEXT NOT NULL,
      source_code TEXT, set_type TEXT DEFAULT 'mock', sort_order INTEGER DEFAULT 0, metadata_json TEXT DEFAULT '{}', active INTEGER DEFAULT 1,
      FOREIGN KEY(program_id) REFERENCES curriculum_programs(id), FOREIGN KEY(collection_id) REFERENCES assessment_collections(id)
    );
    CREATE TABLE IF NOT EXISTS assessment_items(
      assessment_set_id INTEGER NOT NULL, question_id INTEGER NOT NULL, position INTEGER NOT NULL,
      section TEXT, PRIMARY KEY(assessment_set_id, position),
      FOREIGN KEY(assessment_set_id) REFERENCES assessment_sets(id), FOREIGN KEY(question_id) REFERENCES questions(id)
    );
    CREATE TABLE IF NOT EXISTS user_settings(
      id INTEGER PRIMARY KEY CHECK(id=1), exam_date TEXT, daily_target INTEGER DEFAULT 30, timezone TEXT DEFAULT 'Europe/Paris',
      exam_question_time_seconds INTEGER DEFAULT 90, updated_at TEXT
    );
    CREATE TABLE IF NOT EXISTS bookmarks(
      question_id INTEGER PRIMARY KEY, created_at TEXT, FOREIGN KEY(question_id) REFERENCES questions(id)
    );
    CREATE TABLE IF NOT EXISTS notes(
      id INTEGER PRIMARY KEY, question_id INTEGER, concept_id INTEGER, body TEXT NOT NULL, created_at TEXT, updated_at TEXT
    );
    CREATE TABLE IF NOT EXISTS import_jobs(
      id INTEGER PRIMARY KEY, filename TEXT, status TEXT, imported_questions INTEGER DEFAULT 0, imported_concepts INTEGER DEFAULT 0,
      errors_json TEXT DEFAULT '[]', created_at TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_attempts_created ON attempts(created_at);
    CREATE INDEX IF NOT EXISTS idx_attempts_question ON attempts(question_id);
    CREATE INDEX IF NOT EXISTS idx_qm_due ON question_mastery(due_at);
    CREATE INDEX IF NOT EXISTS idx_session_items_session ON session_items(session_id, position);
    CREATE INDEX IF NOT EXISTS idx_assessment_items_set ON assessment_items(assessment_set_id, position);
    ''')
    # Lightweight migrations for databases created by earlier MVP versions.
    topic_cols = {r[1] for r in cur.execute("PRAGMA table_info(topics)")}
    for col, ddl in [("program_id","INTEGER"),("source_label","TEXT"),("canonical_name","TEXT"),("source_code","TEXT"),("source_course_id","INTEGER"),("expected_modules","INTEGER DEFAULT 0"),("source_url","TEXT"),("sort_order","INTEGER DEFAULT 0"),("is_assessment","INTEGER DEFAULT 0")]:
        if col not in topic_cols:
            cur.execute(f"ALTER TABLE topics ADD COLUMN {col} {ddl}")
    module_cols = {r[1] for r in cur.execute("PRAGMA table_info(learning_modules)")}
    for col, ddl in [("source_module_id","TEXT"),("completed","INTEGER DEFAULT 0"),("completed_at","TEXT")]:
        if col not in module_cols:
            cur.execute(f"ALTER TABLE learning_modules ADD COLUMN {col} {ddl}")
    set_cols = {r[1] for r in cur.execute("PRAGMA table_info(assessment_sets)")}
    if "collection_id" not in set_cols:
        cur.execute("ALTER TABLE assessment_sets ADD COLUMN collection_id INTEGER")

    now = datetime.now(timezone.utc).isoformat()
    cur.execute("""INSERT INTO curriculum_programs(slug,name,level,year,source_code,active,created_at) VALUES(?,?,?,?,?,1,?)
                   ON CONFLICT(slug) DO UPDATE SET name=excluded.name,level=excluded.level,year=excluded.year,source_code=excluded.source_code,active=1""",
                (PROGRAM["slug"], PROGRAM["name"], PROGRAM["level"], PROGRAM["year"], PROGRAM["source_code"], now))
    program_id = cur.execute("SELECT id FROM curriculum_programs WHERE slug=?", (PROGRAM["slug"],)).fetchone()[0]
    cur.execute("INSERT OR IGNORE INTO user_settings(id,daily_target,timezone,updated_at) VALUES(1,30,'Europe/Paris',?)", (now,))
    for slug,source_label,canonical_name,min_weight,max_weight,sort_order,course_id,expected_modules in TOPICS:
        source_url = f"https://learn.cfainstitute.org/courses/{course_id}/modules"
        cur.execute("""INSERT INTO topics(program_id,slug,name,min_weight,max_weight,source_label,canonical_name,source_code,source_course_id,expected_modules,source_url,sort_order,is_assessment)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?,?,0)
                       ON CONFLICT(slug) DO UPDATE SET program_id=excluded.program_id,name=excluded.name,min_weight=excluded.min_weight,max_weight=excluded.max_weight,source_label=excluded.source_label,canonical_name=excluded.canonical_name,source_code=excluded.source_code,source_course_id=excluded.source_course_id,expected_modules=excluded.expected_modules,source_url=excluded.source_url,sort_order=excluded.sort_order,is_assessment=0""",
                    (program_id,slug,source_label,min_weight,max_weight,source_label,canonical_name,PROGRAM["source_code"],course_id,expected_modules,source_url,sort_order))
    for slug,name,collection_type,sort_order in ASSESSMENT_COLLECTIONS:
        cur.execute("""INSERT INTO assessment_collections(program_id,slug,name,source_code,collection_type,sort_order,metadata_json,active) VALUES(?,?,?,?,?,?,?,1)
                       ON CONFLICT(slug) DO UPDATE SET program_id=excluded.program_id,name=excluded.name,source_code=excluded.source_code,collection_type=excluded.collection_type,sort_order=excluded.sort_order,active=1""",
                    (program_id,slug,name,PROGRAM["source_code"],collection_type,sort_order,json.dumps({"curriculum":PROGRAM["name"]})))
    for item in DEMO:
        tid = cur.execute("SELECT id FROM topics WHERE slug=?", (item["topic"],)).fetchone()[0]
        cur.execute("INSERT OR IGNORE INTO concepts(topic_id,slug,name,importance) VALUES(?,?,?,?)", (tid,item["concept"],item["concept_name"],1.0))
        cid = cur.execute("SELECT id FROM concepts WHERE slug=?", (item["concept"],)).fetchone()[0]
        opts = item["options"] + [None] * (4-len(item["options"]))
        cur.execute('''INSERT OR IGNORE INTO questions(topic_id,prompt,option_a,option_b,option_c,option_d,correct,explanation,difficulty,question_type,content_version)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?)''', (tid,item["prompt"],opts[0],opts[1],opts[2],opts[3],item["correct"],item["explanation"],item["difficulty"],item.get("type","concept"),"demo-v2"))
        qid = cur.execute("SELECT id FROM questions WHERE prompt=?", (item["prompt"],)).fetchone()[0]
        cur.execute("INSERT OR IGNORE INTO question_concepts(question_id,concept_id,weight) VALUES(?,?,1.0)", (qid,cid))
        if item.get("formula"):
            cur.execute("INSERT OR IGNORE INTO formulas(concept_id,name,expression,explanation) VALUES(?,?,?,?)", (cid,item["concept_name"],item["formula"],item["explanation"]))
    c.commit(); c.close()


def rowdict(row):
    return dict(row) if row is not None else None


def json_load(value, fallback):
    try:
        return json.loads(value) if value else fallback
    except (TypeError, ValueError):
        return fallback
