from __future__ import annotations

import json
from datetime import datetime, timezone

from db import PROGRAM, conn

REQUIRED_QUESTION_FIELDS = {"topic", "prompt", "options", "correct", "explanation"}

TOPIC_ALIASES = {
    "quant": "quant", "quantitative methods": "quant",
    "economics": "economics",
    "corporate": "corporate", "corporate finance": "corporate", "corporate issuers": "corporate",
    "fsa": "fsa", "financial statement analysis": "fsa",
    "equity": "equity", "equities": "equity", "equity investments": "equity",
    "fixed-income": "fixed-income", "fixed income": "fixed-income",
    "derivatives": "derivatives",
    "alternatives": "alternatives", "alternative investments": "alternatives",
    "portfolio": "portfolio", "portfolio construction": "portfolio", "portfolio management": "portfolio",
    "ethics": "ethics", "ethical and professional standards": "ethics",
}


def normalize_topic(value: str) -> str:
    key = str(value or "").strip().lower()
    return TOPIC_ALIASES.get(key, key)


def validate_bundle(bundle: dict) -> list[str]:
    errors = []
    if not isinstance(bundle, dict):
        return ["Root must be a JSON object"]
    program = bundle.get("program") or {}
    if program.get("slug") and program.get("slug") != PROGRAM["slug"]:
        errors.append(f"program.slug must be {PROGRAM['slug']}")
    if program.get("sourceCode") and program.get("sourceCode") != PROGRAM["source_code"]:
        errors.append(f"program.sourceCode must be {PROGRAM['source_code']}")
    if not isinstance(bundle.get("questions", []), list):
        errors.append("questions must be a list")
    for i, q in enumerate(bundle.get("questions", [])):
        missing = REQUIRED_QUESTION_FIELDS - set(q)
        if missing:
            errors.append(f"questions[{i}] missing: {', '.join(sorted(missing))}")
        opts = q.get("options")
        if not isinstance(opts, list) or not 3 <= len(opts) <= 4:
            errors.append(f"questions[{i}].options must have 3 or 4 values")
        if q.get("correct") not in ("A","B","C","D"):
            errors.append(f"questions[{i}].correct must be A/B/C/D")
        if len(opts or []) == 3 and q.get("correct") == "D":
            errors.append(f"questions[{i}] cannot have correct D with 3 options")
        if not q.get("concepts"):
            errors.append(f"questions[{i}] must reference at least one concept slug")
    if not isinstance(bundle.get("assessmentSets", []), list):
        errors.append("assessmentSets must be a list")
    for i, aset in enumerate(bundle.get("assessmentSets", [])):
        if not aset.get("slug") or not aset.get("name"):
            errors.append(f"assessmentSets[{i}] requires slug and name")
        if not isinstance(aset.get("items", []), list):
            errors.append(f"assessmentSets[{i}].items must be a list")
        for j, item in enumerate(aset.get("items", [])):
            if not item.get("questionSourceRef") and not item.get("questionPrompt"):
                errors.append(f"assessmentSets[{i}].items[{j}] requires questionSourceRef or questionPrompt")
    return errors


def import_bundle(bundle: dict, filename: str = "api-upload.json") -> dict:
    errors = validate_bundle(bundle)
    c = conn(); cur = c.cursor()
    created = datetime.now(timezone.utc).isoformat()
    cur.execute("INSERT INTO import_jobs(filename,status,errors_json,created_at) VALUES(?,?,?,?)", (filename,"validating",json.dumps(errors),created))
    job_id = cur.lastrowid
    if errors:
        cur.execute("UPDATE import_jobs SET status='failed' WHERE id=?", (job_id,)); c.commit(); c.close()
        return {"jobId":job_id,"status":"failed","errors":errors}
    imported_concepts = 0; imported_questions = 0; imported_assessments = 0
    try:
        for module in bundle.get("modules", []):
            topic = cur.execute("SELECT id FROM topics WHERE slug=?", (normalize_topic(module["topic"]),)).fetchone()
            if not topic: raise ValueError(f"Unknown topic: {module['topic']}")
            cur.execute('''INSERT INTO learning_modules(topic_id,slug,name,sort_order) VALUES(?,?,?,?)
                           ON CONFLICT(slug) DO UPDATE SET name=excluded.name,sort_order=excluded.sort_order''', (topic[0],module["slug"],module["name"],int(module.get("sortOrder",0))))
        for concept in bundle.get("concepts", []):
            topic = cur.execute("SELECT id FROM topics WHERE slug=?", (normalize_topic(concept["topic"]),)).fetchone()
            if not topic:
                raise ValueError(f"Unknown topic: {concept['topic']}")
            module_id = None
            if concept.get("module"):
                module = cur.execute("SELECT id FROM learning_modules WHERE slug=?", (concept["module"],)).fetchone()
                if module: module_id = module[0]
            cur.execute('''INSERT INTO concepts(topic_id,module_id,slug,name,los,description,importance,prerequisite_slugs)
                           VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(slug) DO UPDATE SET name=excluded.name,los=excluded.los,description=excluded.description,importance=excluded.importance,prerequisite_slugs=excluded.prerequisite_slugs''',
                        (topic[0],module_id,concept["slug"],concept["name"],concept.get("los"),concept.get("description"),float(concept.get("importance",1)),json.dumps(concept.get("prerequisites",[]))))
            imported_concepts += 1
        # Resolve prerequisite graph only after all concepts exist.
        for concept in bundle.get("concepts", []):
            cid = cur.execute("SELECT id FROM concepts WHERE slug=?", (concept["slug"],)).fetchone()[0]
            cur.execute("DELETE FROM concept_prerequisites WHERE concept_id=?", (cid,))
            for prereq_slug in concept.get("prerequisites", []):
                prereq = cur.execute("SELECT id FROM concepts WHERE slug=?", (prereq_slug,)).fetchone()
                if not prereq:
                    raise ValueError(f"Unknown prerequisite concept: {prereq_slug}")
                cur.execute("INSERT INTO concept_prerequisites(concept_id,prerequisite_concept_id) VALUES(?,?)", (cid, prereq[0]))
        for f in bundle.get("formulas", []):
            concept = cur.execute("SELECT id FROM concepts WHERE slug=?", (f.get("concept"),)).fetchone()
            cur.execute("INSERT OR REPLACE INTO formulas(concept_id,name,expression,variables_json,explanation,source_ref) VALUES(?,?,?,?,?,?)",
                        (concept[0] if concept else None,f["name"],f["expression"],json.dumps(f.get("variables",{})),f.get("explanation"),f.get("sourceRef")))
        for q in bundle.get("questions", []):
            topic = cur.execute("SELECT id FROM topics WHERE slug=?", (normalize_topic(q["topic"]),)).fetchone()
            if not topic: raise ValueError(f"Unknown topic: {q['topic']}")
            module = cur.execute("SELECT id FROM learning_modules WHERE slug=?", (q.get("module"),)).fetchone() if q.get("module") else None
            opts=q["options"]+[None]*(4-len(q["options"]))
            cur.execute('''INSERT INTO questions(topic_id,module_id,prompt,option_a,option_b,option_c,option_d,correct,explanation,difficulty,question_type,los,source_ref,content_version,active)
                           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,1)
                           ON CONFLICT(prompt) DO UPDATE SET option_a=excluded.option_a,option_b=excluded.option_b,option_c=excluded.option_c,option_d=excluded.option_d,correct=excluded.correct,explanation=excluded.explanation,difficulty=excluded.difficulty,question_type=excluded.question_type,los=excluded.los,source_ref=excluded.source_ref,content_version=excluded.content_version,active=1''',
                        (topic[0],module[0] if module else None,q["prompt"],opts[0],opts[1],opts[2],opts[3],q["correct"],q["explanation"],int(q.get("difficulty",2)),q.get("type","concept"),q.get("los"),q.get("sourceRef"),bundle.get("version","import")))
            qid=cur.execute("SELECT id FROM questions WHERE prompt=?",(q["prompt"],)).fetchone()[0]
            cur.execute("DELETE FROM question_concepts WHERE question_id=?",(qid,))
            for slug in q.get("concepts",[]):
                cid=cur.execute("SELECT id FROM concepts WHERE slug=?",(slug,)).fetchone()
                if not cid: raise ValueError(f"Question references unknown concept: {slug}")
                cur.execute("INSERT INTO question_concepts(question_id,concept_id,weight) VALUES(?,?,1.0)",(qid,cid[0]))
            cur.execute("DELETE FROM option_concepts WHERE question_id=?", (qid,))
            for option_key, concept_slug in q.get("distractorConcepts", {}).items():
                if option_key not in ("A","B","C","D"):
                    raise ValueError(f"Invalid distractor option key: {option_key}")
                dcid=cur.execute("SELECT id FROM concepts WHERE slug=?",(concept_slug,)).fetchone()
                if not dcid: raise ValueError(f"Unknown distractor concept: {concept_slug}")
                cur.execute("INSERT INTO option_concepts(question_id,option_key,concept_id) VALUES(?,?,?)",(qid,option_key,dcid[0]))
            imported_questions+=1
        program_id = cur.execute("SELECT id FROM curriculum_programs WHERE slug=?", (PROGRAM["slug"],)).fetchone()[0]
        for aset in bundle.get("assessmentSets", []):
            collection_slug = aset.get("collection", "mock-exams")
            collection = cur.execute("SELECT id FROM assessment_collections WHERE slug=? AND program_id=?", (collection_slug, program_id)).fetchone()
            if not collection:
                raise ValueError(f"Unknown assessment collection: {collection_slug}")
            cur.execute("""INSERT INTO assessment_sets(program_id,collection_id,slug,name,source_code,set_type,sort_order,metadata_json,active)
                           VALUES(?,?,?,?,?,?,?,?,1) ON CONFLICT(slug) DO UPDATE SET collection_id=excluded.collection_id,name=excluded.name,source_code=excluded.source_code,set_type=excluded.set_type,sort_order=excluded.sort_order,metadata_json=excluded.metadata_json,active=1""",
                        (program_id, collection[0], aset["slug"], aset["name"], aset.get("sourceCode", PROGRAM["source_code"]), aset.get("type","mock"), int(aset.get("sortOrder",0)), json.dumps(aset.get("metadata",{}))))
            set_id = cur.execute("SELECT id FROM assessment_sets WHERE slug=?", (aset["slug"],)).fetchone()[0]
            cur.execute("DELETE FROM assessment_items WHERE assessment_set_id=?", (set_id,))
            for idx, item in enumerate(aset.get("items", []), 1):
                if item.get("questionSourceRef"):
                    matches = cur.execute("SELECT id FROM questions WHERE source_ref=?", (item["questionSourceRef"],)).fetchall()
                else:
                    matches = cur.execute("SELECT id FROM questions WHERE prompt=?", (item["questionPrompt"],)).fetchall()
                if len(matches) != 1:
                    ref = item.get("questionSourceRef") or item.get("questionPrompt")
                    raise ValueError(f"Assessment item question reference is missing or ambiguous: {ref}")
                cur.execute("INSERT INTO assessment_items(assessment_set_id,question_id,position,section) VALUES(?,?,?,?)",
                            (set_id, matches[0][0], int(item.get("position",idx)), item.get("section")))
            imported_assessments += 1
        cur.execute("UPDATE import_jobs SET status='completed', imported_questions=?, imported_concepts=?, errors_json='[]' WHERE id=?",(imported_questions,imported_concepts,job_id))
        c.commit(); c.close()
        return {"jobId":job_id,"status":"completed","importedQuestions":imported_questions,"importedConcepts":imported_concepts,"importedAssessments":imported_assessments,"errors":[]}
    except Exception as e:
        c.rollback()
        cur.execute("UPDATE import_jobs SET status='failed', errors_json=? WHERE id=?",(json.dumps([str(e)]),job_id)); c.commit(); c.close()
        return {"jobId":job_id,"status":"failed","errors":[str(e)]}
