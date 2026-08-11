from __future__ import annotations

from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from pathlib import Path
from datetime import datetime, timedelta, timezone
import json
import os
import random
import re

from db import conn, init_db, json_load
from content_import import import_bundle
from learning_engine import (
    allocate_mix, confidence_band, days_until, evidence_weight, exam_topic_targets,
    mastery_probability, mistake_reason_label, now_iso, readiness_score,
    recommended_daily_questions, update_srs, weighted_sample_without_replacement,
)

BASE = Path(__file__).parent
UTC = timezone.utc


def fetch_settings(c):
    return dict(c.execute("SELECT * FROM user_settings WHERE id=1").fetchone())


def question_payload(c, qid: int, include_answer=False):
    row = c.execute('''SELECT q.*, t.slug topic_slug, t.name topic_name, lm.name module_name
                       FROM questions q JOIN topics t ON t.id=q.topic_id
                       LEFT JOIN learning_modules lm ON lm.id=q.module_id WHERE q.id=?''', (qid,)).fetchone()
    if not row:
        return None
    options = []
    for key, field in (("A","option_a"),("B","option_b"),("C","option_c"),("D","option_d")):
        if row[field] is not None:
            options.append({"key":key,"text":row[field]})
    concepts = [dict(x) for x in c.execute('''SELECT cp.id, cp.slug, cp.name FROM concepts cp
                    JOIN question_concepts qc ON qc.concept_id=cp.id WHERE qc.question_id=?''',(qid,))]
    payload = {
        "id":row["id"], "prompt":row["prompt"], "options":options, "topic":row["topic_name"],
        "topicSlug":row["topic_slug"], "module":row["module_name"], "difficulty":row["difficulty"],
        "type":row["question_type"], "los":row["los"], "concepts":concepts, "sourceRef":row["source_ref"],
    }
    if include_answer:
        payload.update({"correctAnswer":row["correct"],"explanation":row["explanation"]})
    return payload


def bucket_candidates(c, bucket: str, excluded: set[int]) -> list[dict]:
    now = now_iso()
    if bucket == "due":
        rows = c.execute('''SELECT q.id, 1.8 score FROM question_mastery qm JOIN questions q ON q.id=qm.question_id
                            WHERE q.active=1 AND qm.due_at<=? ORDER BY qm.due_at ASC LIMIT 300''', (now,)).fetchall()
    elif bucket == "errors":
        rows = c.execute('''SELECT q.id, (1.0 + eb.times_wrong*0.35) score FROM error_book eb JOIN questions q ON q.id=eb.question_id
                            WHERE eb.resolved=0 AND q.active=1 ORDER BY eb.last_wrong_at DESC LIMIT 300''').fetchall()
    elif bucket == "weak":
        rows = c.execute('''SELECT DISTINCT q.id,
                         (1.2 + (1.0 - (cm.alpha/(cm.alpha+cm.beta)))*2.0 + cp.importance*0.25) score
                         FROM concept_mastery cm JOIN concepts cp ON cp.id=cm.concept_id
                         JOIN question_concepts qc ON qc.concept_id=cp.id JOIN questions q ON q.id=qc.question_id
                         WHERE q.active=1 AND (cm.alpha/(cm.alpha+cm.beta)) < 0.72
                         ORDER BY score DESC LIMIT 400''').fetchall()
    else:
        rows = c.execute('''SELECT q.id, (1.0 + ((t.min_weight+t.max_weight)/2.0)/20.0) score
                            FROM questions q JOIN topics t ON t.id=q.topic_id
                            WHERE q.active=1 AND NOT EXISTS(SELECT 1 FROM attempts a WHERE a.question_id=q.id)
                            ORDER BY RANDOM() LIMIT 400''').fetchall()
    return [{"id":r["id"],"score":r["score"]} for r in rows if r["id"] not in excluded]


def create_daily_session(c, target: int | None = None):
    settings = fetch_settings(c)
    target = int(target or recommended_daily_questions(settings.get("exam_date"), settings.get("daily_target",30)))
    target = max(5,min(target,120))
    allocation = allocate_mix(target)
    chosen=[]; excluded=set()
    for bucket in ("due","errors","weak","new"):
        picks=weighted_sample_without_replacement(bucket_candidates(c,bucket,excluded), allocation[bucket])
        for p in picks:
            chosen.append((p["id"],bucket)); excluded.add(p["id"])
    if len(chosen)<target:
        fillers=c.execute("SELECT id FROM questions WHERE active=1 ORDER BY RANDOM() LIMIT ?",(target*3,)).fetchall()
        for r in fillers:
            if r["id"] not in excluded:
                chosen.append((r["id"],"fill")); excluded.add(r["id"])
                if len(chosen)>=target: break
    random.shuffle(chosen)
    cur=c.execute("INSERT INTO sessions(mode,status,created_at,target_questions,exam_date_snapshot,metadata_json) VALUES('daily','active',?,?,?,?)",
                  (now_iso(),len(chosen),settings.get("exam_date"),json.dumps({"allocation":allocation})))
    sid=cur.lastrowid
    for i,(qid,bucket) in enumerate(chosen,1):
        c.execute("INSERT INTO session_items(session_id,question_id,position,bucket) VALUES(?,?,?,?)",(sid,qid,i,bucket))
    return sid, len(chosen), allocation

def create_exam_session(c, target=90):
    settings=fetch_settings(c); target=max(10,min(int(target),180))
    topics=[dict(r) for r in c.execute("SELECT * FROM topics WHERE is_assessment=0 ORDER BY sort_order,id")]
    targets=exam_topic_targets(target,topics); chosen=[]; used=set()
    for topic_id,n in targets.items():
        rows=c.execute("SELECT id FROM questions WHERE active=1 AND topic_id=? ORDER BY RANDOM() LIMIT ?",(topic_id,n)).fetchall()
        for r in rows:
            chosen.append((r["id"],"exam-blueprint")); used.add(r["id"])
    if len(chosen)<target:
        for r in c.execute("SELECT id FROM questions WHERE active=1 ORDER BY RANDOM() LIMIT ?",(target*2,)):
            if r["id"] not in used:
                chosen.append((r["id"],"exam-fill")); used.add(r["id"])
                if len(chosen)>=target: break
    random.shuffle(chosen)
    seconds=int(settings.get("exam_question_time_seconds",90))*len(chosen)
    cur=c.execute("INSERT INTO sessions(mode,status,created_at,target_questions,time_limit_seconds,exam_date_snapshot,metadata_json) VALUES('exam','active',?,?,?,?,?)",
                  (now_iso(),len(chosen),seconds,settings.get("exam_date"),json.dumps({"topicTargets":targets})))
    sid=cur.lastrowid
    for i,(qid,bucket) in enumerate(chosen,1): c.execute("INSERT INTO session_items(session_id,question_id,position,bucket) VALUES(?,?,?,?)",(sid,qid,i,bucket))
    return sid,len(chosen),seconds


def create_mock_session(c, assessment_set_id: int):
    settings=fetch_settings(c)
    aset=c.execute("SELECT * FROM assessment_sets WHERE id=? AND active=1", (assessment_set_id,)).fetchone()
    if not aset:
        raise ValueError("Assessment set not found")
    rows=c.execute("SELECT question_id,position,section FROM assessment_items WHERE assessment_set_id=? ORDER BY position", (assessment_set_id,)).fetchall()
    if not rows:
        raise ValueError("Assessment set has no questions")
    seconds=int(settings.get("exam_question_time_seconds",90))*len(rows)
    metadata={"assessmentSetId":assessment_set_id,"assessmentSlug":aset["slug"],"assessmentName":aset["name"]}
    cur=c.execute("INSERT INTO sessions(mode,status,created_at,target_questions,time_limit_seconds,exam_date_snapshot,metadata_json) VALUES('mock','active',?,?,?,?,?)",
                  (now_iso(),len(rows),seconds,settings.get("exam_date"),json.dumps(metadata)))
    sid=cur.lastrowid
    for r in rows:
        c.execute("INSERT INTO session_items(session_id,question_id,position,bucket) VALUES(?,?,?,?)",(sid,r["question_id"],r["position"],f"mock:{r['section'] or 'default'}"))
    return sid,len(rows),seconds

def create_diagnostic_session(c, target=30):
    target=max(10,min(int(target),80)); rows=c.execute('''SELECT q.id, cp.id concept_id FROM concepts cp
              JOIN question_concepts qc ON qc.concept_id=cp.id JOIN questions q ON q.id=qc.question_id
              WHERE q.active=1 GROUP BY cp.id ORDER BY cp.importance DESC, RANDOM() LIMIT ?''',(target,)).fetchall()
    chosen=[]; used=set()
    for r in rows:
        if r["id"] not in used: chosen.append((r["id"],"diagnostic")); used.add(r["id"])
    cur=c.execute("INSERT INTO sessions(mode,status,created_at,target_questions,metadata_json) VALUES('diagnostic','active',?,?,?)",(now_iso(),len(chosen),json.dumps({"baseline":True})))
    sid=cur.lastrowid
    for i,(qid,bucket) in enumerate(chosen,1): c.execute("INSERT INTO session_items(session_id,question_id,position,bucket) VALUES(?,?,?,?)",(sid,qid,i,bucket))
    return sid,len(chosen)


def create_formula_session(c,target=20):
    target=max(5,min(int(target),60)); rows=c.execute('''SELECT DISTINCT q.id FROM questions q
      LEFT JOIN question_concepts qc ON qc.question_id=q.id LEFT JOIN formulas f ON f.concept_id=qc.concept_id
      WHERE q.active=1 AND (q.question_type IN ('formula','calculation') OR f.id IS NOT NULL)
      ORDER BY RANDOM() LIMIT ?''',(target,)).fetchall()
    chosen=[(r["id"],"formula") for r in rows]
    cur=c.execute("INSERT INTO sessions(mode,status,created_at,target_questions,metadata_json) VALUES('formula','active',?,?,?)",(now_iso(),len(chosen),json.dumps({})))
    sid=cur.lastrowid
    for i,(qid,bucket) in enumerate(chosen,1): c.execute("INSERT INTO session_items(session_id,question_id,position,bucket) VALUES(?,?,?,?)",(sid,qid,i,bucket))
    return sid,len(chosen)


def session_next(c,sid:int):
    s=c.execute("SELECT * FROM sessions WHERE id=?",(sid,)).fetchone()
    if not s: return None,None
    item=c.execute("SELECT * FROM session_items WHERE session_id=? AND answered=0 ORDER BY position LIMIT 1",(sid,)).fetchone()
    if not item:
        if s["status"]!="completed": c.execute("UPDATE sessions SET status='completed',completed_at=? WHERE id=?",(now_iso(),sid))
        return dict(s),None
    total=c.execute("SELECT COUNT(*) FROM session_items WHERE session_id=?",(sid,)).fetchone()[0]
    answered=c.execute("SELECT COUNT(*) FROM session_items WHERE session_id=? AND answered=1",(sid,)).fetchone()[0]
    payload=question_payload(c,item["question_id"],False)
    payload.update({"sessionId":sid,"position":item["position"],"total":total,"answered":answered,"bucket":item["bucket"],"mode":s["mode"],"timeLimitSeconds":s["time_limit_seconds"]})
    return dict(s),payload


def update_concept_mastery(c, attempt_id:int, qid:int, correct:bool, assessment:str, difficulty:int, duration_ms:int):
    concepts=c.execute('''SELECT cp.id, cp.importance FROM concepts cp JOIN question_concepts qc ON qc.concept_id=cp.id WHERE qc.question_id=?''',(qid,)).fetchall()
    deltas=[]
    for cp in concepts:
        m=c.execute("SELECT * FROM concept_mastery WHERE concept_id=?",(cp["id"],)).fetchone()
        alpha,beta,exposures,correct_count,avg=(m["alpha"],m["beta"],m["exposures"],m["correct_count"],m["avg_duration_ms"]) if m else (1.0,2.0,0,0,0.0)
        before=mastery_probability(alpha,beta)
        pos,neg=evidence_weight(correct,assessment,difficulty,duration_ms)
        alpha+=pos*float(cp["importance"]); beta+=neg
        exposures+=1; correct_count+=int(correct); avg=((avg*(exposures-1))+duration_ms)/max(1,exposures)
        after=mastery_probability(alpha,beta)
        c.execute('''INSERT INTO concept_mastery(concept_id,alpha,beta,exposures,correct_count,avg_duration_ms,last_seen_at)
                     VALUES(?,?,?,?,?,?,?) ON CONFLICT(concept_id) DO UPDATE SET alpha=excluded.alpha,beta=excluded.beta,exposures=excluded.exposures,correct_count=excluded.correct_count,avg_duration_ms=excluded.avg_duration_ms,last_seen_at=excluded.last_seen_at''',
                  (cp["id"],alpha,beta,exposures,correct_count,avg,now_iso()))
        c.execute("INSERT INTO mastery_events(concept_id,attempt_id,probability_before,probability_after,created_at) VALUES(?,?,?,?,?)",(cp["id"],attempt_id,before,after,now_iso()))
        deltas.append({"conceptId":cp["id"],"before":round(before,4),"after":round(after,4)})
    return deltas

def dashboard_data(c):
    now=datetime.now(UTC); d7=(now-timedelta(days=7)).isoformat(); d30=(now-timedelta(days=30)).isoformat()
    total=c.execute("SELECT COUNT(*) FROM attempts").fetchone()[0]
    def window(since):
        r=c.execute("SELECT COUNT(*) n, COALESCE(SUM(correct),0) good, AVG(duration_ms) avg_ms FROM attempts WHERE created_at>=?",(since,)).fetchone()
        return {"attempts":r["n"],"accuracy":round(100*r["good"]/r["n"],1) if r["n"] else 0,"avgSeconds":round((r["avg_ms"] or 0)/1000,1)}
    w7=window(d7); w30=window(d30)
    concepts=[]
    for r in c.execute('''SELECT cp.id,cp.slug,cp.name,cp.importance,t.name topic_name,
                   COALESCE(cm.alpha,1.0) alpha,COALESCE(cm.beta,2.0) beta,COALESCE(cm.exposures,0) exposures,
                   COALESCE(cm.avg_duration_ms,0) avg_duration_ms
                   FROM concepts cp JOIN topics t ON t.id=cp.topic_id LEFT JOIN concept_mastery cm ON cm.concept_id=cp.id'''):
        p=mastery_probability(r["alpha"],r["beta"])
        delta=c.execute("SELECT COALESCE(SUM(probability_after-probability_before),0) FROM mastery_events WHERE concept_id=? AND created_at>=?",(r["id"],d30)).fetchone()[0]
        concepts.append({"id":r["id"],"slug":r["slug"],"name":r["name"],"topic":r["topic_name"],"probability":round(p,3),"masteryPercent":round(p*100),"band":confidence_band(p,r["exposures"]),"exposures":r["exposures"],"importance":r["importance"],"delta30":round(delta*100,1),"avgSeconds":round(r["avg_duration_ms"]/1000,1)})
    answered_questions=c.execute("SELECT COUNT(DISTINCT question_id) FROM attempts").fetchone()[0]
    active_questions=c.execute("SELECT COUNT(*) FROM questions WHERE active=1").fetchone()[0]
    coverage=answered_questions/max(1,active_questions)
    readiness=readiness_score(concepts,w30["accuracy"],coverage,w30["avgSeconds"] or None)
    topics=[]
    for t in c.execute("SELECT * FROM topics WHERE is_assessment=0 ORDER BY sort_order,id"):
        a=c.execute('''SELECT COUNT(*) n,COALESCE(SUM(a.correct),0) good,AVG(a.duration_ms) avg_ms FROM attempts a JOIN questions q ON q.id=a.question_id WHERE q.topic_id=?''',(t["id"],)).fetchone()
        cm=c.execute('''SELECT AVG(cm.alpha/(cm.alpha+cm.beta)) p FROM concept_mastery cm JOIN concepts cp ON cp.id=cm.concept_id WHERE cp.topic_id=?''',(t["id"],)).fetchone()
        topics.append({"name":t["name"],"slug":t["slug"],"attempts":a["n"],"accuracy":round(100*a["good"]/a["n"]) if a["n"] else 0,"mastery":round(100*(cm["p"] or 0)),"avgSeconds":round((a["avg_ms"] or 0)/1000,1),"minWeight":t["min_weight"],"maxWeight":t["max_weight"]})
    due=c.execute("SELECT COUNT(*) FROM question_mastery WHERE due_at<=?",(now_iso(),)).fetchone()[0]
    errors=c.execute("SELECT COUNT(*) FROM error_book WHERE resolved=0").fetchone()[0]
    dates=[r[0] for r in c.execute("SELECT DISTINCT substr(created_at,1,10) d FROM attempts ORDER BY d DESC LIMIT 365")]
    streak=0; expected=now.date()
    if dates and datetime.fromisoformat(dates[0]).date()==expected-timedelta(days=1): expected-=timedelta(days=1)
    for d in dates:
        current=datetime.fromisoformat(d).date()
        if current==expected:
            streak+=1; expected-=timedelta(days=1)
        elif current<expected: break
    settings=fetch_settings(c)
    return {"attempts":total,"window7":w7,"window30":w30,"coverage":round(coverage*100,1),"readiness":readiness,"due":due,"openErrors":errors,"streak":streak,"topics":topics,"concepts":sorted(concepts,key=lambda x:(x["masteryPercent"],-x["importance"]))[:40],"settings":settings}


def plan_data(c):
    settings=fetch_settings(c); days=days_until(settings.get("exam_date")); daily=recommended_daily_questions(settings.get("exam_date"),settings.get("daily_target",30))
    active_q=c.execute("SELECT COUNT(*) FROM questions WHERE active=1").fetchone()[0]; seen=c.execute("SELECT COUNT(DISTINCT question_id) FROM attempts").fetchone()[0]
    unseen=max(0,active_q-seen); weeks=max(1,(days or 84)//7)
    if days is None:
        phases=[{"name":"Coverage","share":45},{"name":"Consolidation","share":35},{"name":"Mock & review","share":20}]
    elif days>60:
        phases=[{"name":"Coverage","days":max(1,days-45)},{"name":"Consolidation","days":30},{"name":"Exam mode","days":15}]
    elif days>21:
        phases=[{"name":"Consolidation","days":max(1,days-14)},{"name":"Exam mode","days":14}]
    else:
        phases=[{"name":"Exam mode + Error Book","days":max(1,days)}]
    return {"examDate":settings.get("exam_date"),"daysUntilExam":days,"recommendedDailyQuestions":daily,"unseenQuestions":unseen,"weeksRemaining":weeks,"phases":phases}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args): print(f"{self.address_string()} - {fmt % args}")

    def send_json(self,obj,status=200):
        body=json.dumps(obj,ensure_ascii=False).encode(); self.send_response(status); self.send_header("Content-Type","application/json; charset=utf-8"); self.send_header("Cache-Control","no-store"); self.send_header("Content-Length",str(len(body))); self.end_headers(); self.wfile.write(body)

    def send_file(self,path,ctype):
        data=(BASE/path).read_bytes(); self.send_response(200); self.send_header("Content-Type",ctype); self.send_header("Content-Length",str(len(data))); self.end_headers(); self.wfile.write(data)

    def read_json(self):
        n=int(self.headers.get("Content-Length","0")); raw=self.rfile.read(n); return json.loads(raw or b"{}")

    def do_GET(self):
        parsed=urlparse(self.path); p=parsed.path
        if p=="/health": return self.send_json({"status":"ok","engine":"adaptive-v4","curriculum":"CFA Level I 2027"})
        c=conn()
        try:
            if p=="/api/curriculum":
                program = c.execute("SELECT * FROM curriculum_programs WHERE active=1 ORDER BY year DESC,id DESC LIMIT 1").fetchone()
                if not program: return self.send_json({"error":"Curriculum not initialized"},404)
                topics = [dict(r) for r in c.execute("""SELECT t.slug,t.name,t.source_label,t.canonical_name,t.source_code,t.source_course_id,t.expected_modules,t.source_url,t.sort_order,t.min_weight,t.max_weight,
                    (SELECT COUNT(*) FROM learning_modules lm WHERE lm.topic_id=t.id) imported_modules,
                    (SELECT COUNT(*) FROM learning_modules lm WHERE lm.topic_id=t.id AND COALESCE(lm.completed,0)=1) completed_modules
                    FROM topics t WHERE t.program_id=? AND t.is_assessment=0 ORDER BY t.sort_order,t.id""", (program["id"],))]
                assessments = []
                for r in c.execute("""SELECT ac.id,ac.slug,ac.name,ac.source_code,ac.collection_type,ac.sort_order,ac.metadata_json,
                           (SELECT COUNT(*) FROM assessment_sets aset WHERE aset.collection_id=ac.id AND aset.active=1) set_count
                    FROM assessment_collections ac WHERE ac.program_id=? AND ac.active=1 ORDER BY ac.sort_order,ac.id""", (program["id"],)):
                    d=dict(r); d["metadata"]=json_load(d.pop("metadata_json",None),{}); assessments.append(d)
                total_expected = sum(int(t.get("expected_modules") or 0) for t in topics)
                total_imported = sum(int(t.get("imported_modules") or 0) for t in topics)
                total_completed = sum(int(t.get("completed_modules") or 0) for t in topics)
                summary = {
                    "totalTopics": len(topics),
                    "totalExpectedModules": total_expected,
                    "totalImportedModules": total_imported,
                    "totalCompletedModules": total_completed,
                    "corpusCoveragePercent": round((100 * total_imported / total_expected), 1) if total_expected else 0,
                    "studyCompletionPercent": round((100 * total_completed / total_expected), 1) if total_expected else 0,
                }
                return self.send_json({"program":dict(program),"topics":topics,"assessments":assessments,"summary":summary})
            if p=="/api/assessments":
                rows=[]
                for r in c.execute("""SELECT aset.id,aset.slug,aset.name,aset.source_code,aset.set_type,aset.sort_order,aset.metadata_json,
                       ac.slug collection_slug,ac.name collection_name,COUNT(ai.question_id) item_count
                       FROM assessment_sets aset LEFT JOIN assessment_collections ac ON ac.id=aset.collection_id
                       LEFT JOIN assessment_items ai ON ai.assessment_set_id=aset.id
                       WHERE aset.active=1 GROUP BY aset.id ORDER BY ac.sort_order,aset.sort_order,aset.id"""):
                    d=dict(r); d["metadata"]=json_load(d.pop("metadata_json",None),{}); rows.append(d)
                return self.send_json({"assessmentSets":rows})
            if p=="/api/dashboard": return self.send_json(dashboard_data(c))
            if p=="/api/plan": return self.send_json(plan_data(c))
            if p=="/api/settings": return self.send_json(fetch_settings(c))
            if p=="/api/concepts": return self.send_json({"concepts":dashboard_data(c)["concepts"]})
            if p=="/api/formulas":
                rows=[dict(r) for r in c.execute('''SELECT f.*,cp.name concept_name,cp.slug concept_slug,t.name topic_name FROM formulas f
                    LEFT JOIN concepts cp ON cp.id=f.concept_id LEFT JOIN topics t ON t.id=cp.topic_id ORDER BY t.id,cp.name''')]
                for r in rows: r["variables"]=json_load(r.pop("variables_json",None),{})
                return self.send_json({"formulas":rows})
            if p=="/api/errors":
                rows=[]
                for r in c.execute('''SELECT eb.*,q.prompt,q.correct,q.explanation,cp.name concept_name,t.name topic_name
                      FROM error_book eb JOIN questions q ON q.id=eb.question_id LEFT JOIN concepts cp ON cp.id=eb.concept_id
                      JOIN topics t ON t.id=q.topic_id ORDER BY eb.resolved ASC, eb.last_wrong_at DESC'''):
                    d=dict(r); d["reasonLabel"]=mistake_reason_label(d.get("mistake_reason")); rows.append(d)
                return self.send_json({"errors":rows})
            if p=="/api/bookmarks":
                return self.send_json({"bookmarks":[question_payload(c,r[0],False) for r in c.execute("SELECT question_id FROM bookmarks ORDER BY created_at DESC")]})
            if p=="/api/concept-map":
                nodes=[]
                for r in c.execute('''SELECT cp.id,cp.slug,cp.name,t.name topic_name,cp.importance,COALESCE(cm.alpha,1.0) alpha,COALESCE(cm.beta,2.0) beta,COALESCE(cm.exposures,0) exposures FROM concepts cp JOIN topics t ON t.id=cp.topic_id LEFT JOIN concept_mastery cm ON cm.concept_id=cp.id ORDER BY t.id,cp.name'''):
                    d=dict(r); pval=mastery_probability(d.pop("alpha"),d.pop("beta")); d["masteryPercent"]=round(pval*100); d["band"]=confidence_band(pval,d["exposures"]); nodes.append(d)
                edges=[{"from":r["prerequisite_concept_id"],"to":r["concept_id"]} for r in c.execute("SELECT * FROM concept_prerequisites")]
                return self.send_json({"nodes":nodes,"edges":edges})
            if p=="/api/confusions":
                rows=[dict(r) for r in c.execute('''SELECT cf.count,cf.last_seen_at,a.name correct_concept,b.name confused_with,ta.name topic_name FROM confusions cf JOIN concepts a ON a.id=cf.correct_concept_id JOIN concepts b ON b.id=cf.confused_with_concept_id JOIN topics ta ON ta.id=a.topic_id ORDER BY cf.count DESC,cf.last_seen_at DESC LIMIT 50''')]
                return self.send_json({"confusions":rows})
            if p=="/api/import/schema":
                return self.send_json({"version":"2027.1","bundle":{"program":{"slug":"cfa-program-level-i-2027","name":"CFA Program – Level I 2027","sourceCode":"CFA-27-02-LI-B"},"version":"2027.1","modules":[{"topic":"quant","slug":"time-value-money","name":"Time Value of Money","sortOrder":1}],"concepts":[{"topic":"quant","module":"time-value-money","slug":"future-value","name":"Future Value","los":"...","importance":1.2,"prerequisites":[]}],"formulas":[{"concept":"future-value","name":"Future Value","expression":"FV = PV(1+r)^n","variables":{"PV":"present value"}}],"questions":[{"topic":"quant","module":"time-value-money","concepts":["future-value"],"prompt":"...","options":["...","...","..."],"correct":"A","explanation":"...","difficulty":2,"type":"calculation","los":"...","sourceRef":"your-source-id","distractorConcepts":{"B":"confused-concept-slug"}}],"assessmentSets":[{"collection":"mock-exams","slug":"mock-exam-1","name":"Mock Exam 1","type":"mock","sourceCode":"CFA-27-02-LI-B","items":[{"questionSourceRef":"your-source-id","position":1,"section":"session-1"}]}]}})
            m=re.fullmatch(r"/api/sessions/(\d+)/next",p)
            if m:
                s,q=session_next(c,int(m.group(1))); c.commit(); return self.send_json({"session":s,"question":q,"complete":q is None})
            m=re.fullmatch(r"/api/sessions/(\d+)/summary",p)
            if m:
                sid=int(m.group(1)); s=c.execute("SELECT * FROM sessions WHERE id=?",(sid,)).fetchone()
                if not s: return self.send_json({"error":"Session not found"},404)
                rows=[dict(r) for r in c.execute('''SELECT a.*,q.prompt,q.correct correct_answer,q.explanation,t.name topic_name FROM attempts a JOIN questions q ON q.id=a.question_id JOIN topics t ON t.id=q.topic_id WHERE a.session_id=? ORDER BY a.id''',(sid,))]
                n=len(rows); good=sum(r["correct"] for r in rows)
                return self.send_json({"session":dict(s),"attempts":rows,"score":round(100*good/n,1) if n else 0})
        finally:
            c.close()
        if p in ("/","/curriculum","/practice","/dashboard","/exam","/formulas","/errors","/plan","/settings","/import","/map"): return self.send_file("static/index.html","text/html; charset=utf-8")
        if p=="/app.js": return self.send_file("static/app.js","text/javascript; charset=utf-8")
        if p=="/style.css": return self.send_file("static/style.css","text/css; charset=utf-8")
        return self.send_error(404)

    def do_POST(self):
        p=urlparse(self.path).path
        try: data=self.read_json()
        except Exception: return self.send_json({"error":"Invalid JSON"},400)
        c=conn()
        try:
            if p=="/api/settings":
                exam=data.get("examDate"); daily=max(5,min(int(data.get("dailyTarget",30)),120)); qtime=max(30,min(int(data.get("examQuestionTimeSeconds",90)),240))
                c.execute("UPDATE user_settings SET exam_date=?,daily_target=?,exam_question_time_seconds=?,updated_at=? WHERE id=1",(exam,daily,qtime,now_iso())); c.commit(); return self.send_json(fetch_settings(c))
            if p=="/api/sessions":
                mode=data.get("mode","daily"); target=data.get("target")
                if mode=="daily": sid,n,alloc=create_daily_session(c,target); extra={"allocation":alloc}
                elif mode=="exam": sid,n,seconds=create_exam_session(c,target or 90); extra={"timeLimitSeconds":seconds}
                elif mode=="mock": sid,n,seconds=create_mock_session(c,int(data.get("assessmentSetId"))); extra={"timeLimitSeconds":seconds,"assessmentSetId":int(data.get("assessmentSetId"))}
                elif mode=="diagnostic": sid,n=create_diagnostic_session(c,target or 30); extra={}
                elif mode=="formula": sid,n=create_formula_session(c,target or 20); extra={}
                else: return self.send_json({"error":"Unsupported session mode"},400)
                c.commit(); return self.send_json({"sessionId":sid,"mode":mode,"questions":n,**extra},201)
            if p=="/api/attempt":
                qid=int(data["questionId"]); sid=int(data.get("sessionId")) if data.get("sessionId") else None; ans=data.get("answer")
                assessment=data.get("selfAssessment","guessed"); reason=data.get("mistakeReason"); duration=max(0,int(data.get("durationMs",0)))
                if ans not in ("A","B","C","D") or assessment not in ("knew","guessed","didnt_know"): return self.send_json({"error":"Invalid attempt"},400)
                q=c.execute("SELECT * FROM questions WHERE id=?",(qid,)).fetchone()
                if not q: return self.send_json({"error":"Question not found"},404)
                correct=ans==q["correct"]; now=now_iso()
                cur=c.execute("INSERT INTO attempts(question_id,session_id,answer,correct,self_assessment,mistake_reason,duration_ms,created_at) VALUES(?,?,?,?,?,?,?,?)",(qid,sid,ans,int(correct),assessment,reason,duration,now)); attempt_id=cur.lastrowid
                m=c.execute("SELECT * FROM question_mastery WHERE question_id=?",(qid,)).fetchone(); ease,interval,reps=(m["ease"],m["interval_days"],m["repetitions"]) if m else (2.5,0,0)
                ease,interval,reps,due=update_srs(ease,interval,reps,correct,assessment)
                c.execute('''INSERT INTO question_mastery(question_id,ease,interval_days,repetitions,due_at,last_correct,last_seen_at) VALUES(?,?,?,?,?,?,?)
                           ON CONFLICT(question_id) DO UPDATE SET ease=excluded.ease,interval_days=excluded.interval_days,repetitions=excluded.repetitions,due_at=excluded.due_at,last_correct=excluded.last_correct,last_seen_at=excluded.last_seen_at''',(qid,ease,interval,reps,due,int(correct),now))
                deltas=update_concept_mastery(c,attempt_id,qid,correct,assessment,q["difficulty"],duration)
                concept_ids=[r[0] for r in c.execute("SELECT concept_id FROM question_concepts WHERE question_id=?",(qid,))]
                if not correct:
                    confused = [r[0] for r in c.execute("SELECT concept_id FROM option_concepts WHERE question_id=? AND option_key=?", (qid, ans))]
                    for correct_cid in concept_ids:
                        for confused_cid in confused:
                            if correct_cid != confused_cid:
                                c.execute('''INSERT INTO confusions(correct_concept_id,confused_with_concept_id,count,last_seen_at) VALUES(?,?,1,?)
                                  ON CONFLICT(correct_concept_id,confused_with_concept_id) DO UPDATE SET count=count+1,last_seen_at=excluded.last_seen_at''', (correct_cid,confused_cid,now))
                if (not correct) or assessment!="knew":
                    eb_reason=reason or ("guess" if assessment=="guessed" else "knowledge")
                    for cid in (concept_ids or [None]):
                        c.execute('''INSERT INTO error_book(question_id,concept_id,mistake_reason,times_wrong,last_wrong_at,resolved)
                            VALUES(?,?,?,?,?,0) ON CONFLICT(question_id,concept_id,mistake_reason) DO UPDATE SET times_wrong=times_wrong+1,last_wrong_at=excluded.last_wrong_at,resolved=0''',(qid,cid,eb_reason,1,now))
                elif correct and assessment=="knew":
                    c.execute("UPDATE error_book SET resolved=1 WHERE question_id=? AND times_wrong<=2",(qid,))
                mode=None
                if sid:
                    s=c.execute("SELECT * FROM sessions WHERE id=?",(sid,)).fetchone(); mode=s["mode"] if s else None
                    c.execute("UPDATE session_items SET answered=1 WHERE session_id=? AND question_id=?",(sid,qid))
                    remaining=c.execute("SELECT COUNT(*) FROM session_items WHERE session_id=? AND answered=0",(sid,)).fetchone()[0]
                    if remaining==0: c.execute("UPDATE sessions SET status='completed',completed_at=? WHERE id=?",(now_iso(),sid))
                c.commit()
                if mode in ("exam","mock"): return self.send_json({"accepted":True,"deferredCorrection":True,"masteryDelta":deltas,"nextDueAt":due})
                return self.send_json({"accepted":True,"correct":correct,"correctAnswer":q["correct"],"explanation":q["explanation"],"masteryDelta":deltas,"nextDueAt":due})
            if p=="/api/modules/complete":
                module_id=int(data["moduleId"]); completed=1 if data.get("completed",True) else 0
                module=c.execute("SELECT id FROM learning_modules WHERE id=?",(module_id,)).fetchone()
                if not module: return self.send_json({"error":"Module not found"},404)
                c.execute("UPDATE learning_modules SET completed=?,completed_at=? WHERE id=?",(completed,now_iso() if completed else None,module_id)); c.commit()
                return self.send_json({"ok":True,"moduleId":module_id,"completed":bool(completed)})
            if p=="/api/errors/reason":
                qid=int(data["questionId"]); reason=str(data.get("mistakeReason","knowledge"))
                latest=c.execute("SELECT id FROM attempts WHERE question_id=? ORDER BY id DESC LIMIT 1",(qid,)).fetchone()
                if latest: c.execute("UPDATE attempts SET mistake_reason=? WHERE id=?",(reason,latest[0]))
                c.execute("UPDATE error_book SET mistake_reason=? WHERE question_id=? AND resolved=0",(reason,qid))
                c.commit(); return self.send_json({"ok":True})
            if p=="/api/errors/resolve":
                eid=int(data["errorId"]); c.execute("UPDATE error_book SET resolved=? WHERE id=?",(1 if data.get("resolved",True) else 0,eid)); c.commit(); return self.send_json({"ok":True})
            if p=="/api/bookmarks/toggle":
                qid=int(data["questionId"]); exists=c.execute("SELECT 1 FROM bookmarks WHERE question_id=?",(qid,)).fetchone()
                if exists: c.execute("DELETE FROM bookmarks WHERE question_id=?",(qid,)); bookmarked=False
                else: c.execute("INSERT INTO bookmarks(question_id,created_at) VALUES(?,?)",(qid,now_iso())); bookmarked=True
                c.commit(); return self.send_json({"bookmarked":bookmarked})
            if p=="/api/notes":
                body=str(data.get("body","")).strip()
                if not body: return self.send_json({"error":"Empty note"},400)
                c.execute("INSERT INTO notes(question_id,concept_id,body,created_at,updated_at) VALUES(?,?,?,?,?)",(data.get("questionId"),data.get("conceptId"),body,now_iso(),now_iso())); c.commit(); return self.send_json({"ok":True},201)
            if p=="/api/import":
                c.close(); result=import_bundle(data.get("bundle",data),data.get("filename","api-upload.json")); return self.send_json(result,201 if result.get("status")=="completed" else 400)
        except (KeyError,ValueError,TypeError) as e:
            c.rollback(); return self.send_json({"error":"Invalid request","detail":str(e)},400)
        finally:
            try: c.close()
            except Exception: pass
        return self.send_error(404)


if __name__=="__main__":
    init_db(); port=int(os.environ.get("PORT","3000")); print(f"CFA Learning adaptive-v4 · Level I 2027 listening on :{port}"); ThreadingHTTPServer(("0.0.0.0",port),Handler).serve_forever()
