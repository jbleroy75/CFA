from __future__ import annotations

from datetime import datetime, timedelta, timezone
from http.server import ThreadingHTTPServer
from urllib.parse import urlparse
import json
import os

from db import conn, init_db, json_load
from learning_engine import mastery_probability, confidence_band, now_iso, weighted_sample_without_replacement
from module1_seed import CONTENT_PATH, seed_module1
from server import Handler as BaseHandler

UTC = timezone.utc
MODULE_SLUG = "quant-m01-returns-financial-assets"


def module_content():
    return json.loads(CONTENT_PATH.read_text(encoding="utf-8"))


def module_row(c):
    return c.execute("SELECT lm.*,t.name topic_name,t.slug topic_slug FROM learning_modules lm JOIN topics t ON t.id=lm.topic_id WHERE lm.slug=?", (MODULE_SLUG,)).fetchone()


def module_snapshot(c):
    content = module_content(); lm = module_row(c)
    if not lm:
        raise ValueError("Module 1 is not initialized")
    mid = lm["id"]
    now = datetime.now(UTC); d7=(now-timedelta(days=7)).isoformat(); d30=(now-timedelta(days=30)).isoformat()

    concept_rows=[]
    for r in c.execute('''SELECT cp.id,cp.slug,cp.name,cp.description,cp.importance,cp.prerequisite_slugs,
                       COALESCE(cm.alpha,1.0) alpha,COALESCE(cm.beta,2.0) beta,COALESCE(cm.exposures,0) exposures,
                       COALESCE(cm.correct_count,0) correct_count,COALESCE(cm.avg_duration_ms,0) avg_duration_ms
                       FROM concepts cp LEFT JOIN concept_mastery cm ON cm.concept_id=cp.id
                       WHERE cp.module_id=? ORDER BY cp.id''', (mid,)):
        d=dict(r); p=mastery_probability(d.pop("alpha"),d.pop("beta"))
        d["masteryPercent"]=round(p*100); d["probability"]=round(p,4); d["band"]=confidence_band(p,d["exposures"])
        d["accuracy"] = round(100*d["correct_count"]/d["exposures"],1) if d["exposures"] else 0
        d["avgSeconds"] = round(d["avg_duration_ms"]/1000,1)
        d["prerequisites"] = json_load(d.pop("prerequisite_slugs", None), [])
        cfg = next((x for x in content["concepts"] if x["slug"]==d["slug"]), {})
        d["intuition"] = cfg.get("intuition",""); d["traps"] = cfg.get("traps",[])
        concept_rows.append(d)

    def perf(since):
        r=c.execute('''SELECT COUNT(*) n,COALESCE(SUM(a.correct),0) good,AVG(a.duration_ms) avg_ms
                     FROM attempts a JOIN questions q ON q.id=a.question_id WHERE q.module_id=? AND a.created_at>=?''',(mid,since)).fetchone()
        return {"attempts":r["n"],"accuracy":round(100*r["good"]/r["n"],1) if r["n"] else 0,"avgSeconds":round((r["avg_ms"] or 0)/1000,1)}

    w7=perf(d7); w30=perf(d30)
    qcount=c.execute("SELECT COUNT(*) FROM questions WHERE module_id=? AND active=1",(mid,)).fetchone()[0]
    seen=c.execute("SELECT COUNT(DISTINCT a.question_id) FROM attempts a JOIN questions q ON q.id=a.question_id WHERE q.module_id=?",(mid,)).fetchone()[0]
    due=c.execute('''SELECT COUNT(*) FROM question_mastery qm JOIN questions q ON q.id=qm.question_id WHERE q.module_id=? AND qm.due_at<=?''',(mid,now_iso())).fetchone()[0]
    open_errors=c.execute('''SELECT COUNT(*) FROM error_book eb JOIN questions q ON q.id=eb.question_id WHERE q.module_id=? AND eb.resolved=0''',(mid,)).fetchone()[0]
    avg_mastery = round(sum(x["probability"]*x["importance"] for x in concept_rows)/max(0.0001,sum(x["importance"] for x in concept_rows))*100) if concept_rows else 0
    min_mastery = min((x["masteryPercent"] for x in concept_rows), default=0)
    min_exposures = min((x["exposures"] for x in concept_rows), default=0)
    pol=content["masteryPolicy"]
    mastered = avg_mastery >= round(pol["masteredThreshold"]*100) and min_mastery >= round(pol["minimumConceptThreshold"]*100) and min_exposures >= pol["minimumExposuresPerConcept"] and w30["accuracy"] >= pol["targetAccuracy30d"]*100
    status = "mastered" if mastered else ("exam-ready" if avg_mastery>=75 and min_mastery>=60 else ("developing" if avg_mastery>=55 else "building"))

    formulas=[]
    for r in c.execute('''SELECT f.id,f.name,f.expression,f.variables_json,f.explanation,cp.slug concept_slug,cp.name concept_name FROM formulas f JOIN concepts cp ON cp.id=f.concept_id WHERE cp.module_id=? ORDER BY f.id''',(mid,)):
        d=dict(r); d["variables"]=json_load(d.pop("variables_json",None),{}); formulas.append(d)
    confusions=[dict(r) for r in c.execute('''SELECT cf.count,cf.last_seen_at,a.name correct_concept,b.name confused_with FROM confusions cf JOIN concepts a ON a.id=cf.correct_concept_id JOIN concepts b ON b.id=cf.confused_with_concept_id WHERE a.module_id=? ORDER BY cf.count DESC LIMIT 10''',(mid,))]

    return {
        "module":{"id":mid,"slug":lm["slug"],"name":lm["name"],"topic":lm["topic_name"],"completed":bool(lm["completed"]),"moduleNumber":content["moduleNumber"]},
        "sourceInventory":content["sourceInventory"],"taxonomy":content["taxonomy"],"masteryPolicy":pol,"learningPath":content["learningPath"],
        "stats":{"mastery":avg_mastery,"status":status,"mastered":mastered,"questionBank":qcount,"seenQuestions":seen,"coverage":round(100*seen/max(1,qcount),1),"due":due,"openErrors":open_errors,"window7":w7,"window30":w30},
        "concepts":concept_rows,"formulas":formulas,"flashcards":content["flashcards"],"confusions":confusions
    }


def candidate_rows(c, mid:int, mode:str):
    now=now_iso()
    if mode=="weak":
        rows=c.execute('''SELECT DISTINCT q.id,(2.5-(COALESCE(cm.alpha,1.0)/(COALESCE(cm.alpha,1.0)+COALESCE(cm.beta,2.0)))) score FROM questions q JOIN question_concepts qc ON qc.question_id=q.id JOIN concepts cp ON cp.id=qc.concept_id LEFT JOIN concept_mastery cm ON cm.concept_id=cp.id WHERE q.module_id=? AND q.active=1 ORDER BY score DESC''',(mid,)).fetchall()
    elif mode=="formula":
        rows=c.execute('''SELECT DISTINCT q.id,1.4 score FROM questions q JOIN question_concepts qc ON qc.question_id=q.id JOIN concepts cp ON cp.id=qc.concept_id LEFT JOIN formulas f ON f.concept_id=cp.id WHERE q.module_id=? AND q.active=1 AND (q.question_type='calculation' OR f.id IS NOT NULL) ORDER BY RANDOM()''',(mid,)).fetchall()
    elif mode=="diagnostic":
        rows=c.execute('''SELECT q.id,(1.0+cp.importance) score FROM concepts cp JOIN question_concepts qc ON qc.concept_id=cp.id JOIN questions q ON q.id=qc.question_id WHERE cp.module_id=? AND q.active=1 GROUP BY cp.id ORDER BY cp.importance DESC''',(mid,)).fetchall()
    else:
        rows=c.execute('''SELECT q.id,(1.0 + CASE WHEN qm.due_at<=? THEN 1.5 ELSE 0 END + CASE WHEN eb.resolved=0 THEN MIN(1.5,0.25*eb.times_wrong) ELSE 0 END + (1-(COALESCE(cm.alpha,1.0)/(COALESCE(cm.alpha,1.0)+COALESCE(cm.beta,2.0)))) ) score FROM questions q LEFT JOIN question_mastery qm ON qm.question_id=q.id LEFT JOIN error_book eb ON eb.question_id=q.id LEFT JOIN question_concepts qc ON qc.question_id=q.id LEFT JOIN concept_mastery cm ON cm.concept_id=qc.concept_id WHERE q.module_id=? AND q.active=1 GROUP BY q.id ORDER BY score DESC''',(now,mid)).fetchall()
    return [{"id":r["id"],"score":float(r["score"] or 1)} for r in rows]


def create_module_session(c, mode:str, target:int):
    lm=module_row(c)
    if not lm: raise ValueError("Module 1 not found")
    mid=lm["id"]
    if mode=="exam":
        target=max(10,min(target,34)); ids=[r[0] for r in c.execute("SELECT id FROM questions WHERE module_id=? AND active=1 ORDER BY RANDOM() LIMIT ?",(mid,target))]
        session_mode="exam"; seconds=90*len(ids); metadata={"scope":"module","moduleSlug":MODULE_SLUG,"moduleName":lm["name"],"assessment":"module-exam"}
    else:
        limits={"diagnostic":12,"weak":15,"formula":12,"quick":8,"practice":20}
        target=max(5,min(target or limits.get(mode,20),40)); rows=candidate_rows(c,mid,mode)
        picked=weighted_sample_without_replacement(rows,target); ids=[x["id"] for x in picked]
        session_mode="module"; seconds=None; metadata={"scope":"module","moduleSlug":MODULE_SLUG,"moduleName":lm["name"],"moduleMode":mode}
    cur=c.execute("INSERT INTO sessions(mode,status,created_at,target_questions,time_limit_seconds,metadata_json) VALUES(?,?,?,?,?,?)",(session_mode,"active",now_iso(),len(ids),seconds,json.dumps(metadata)))
    sid=cur.lastrowid
    for pos,qid in enumerate(ids,1): c.execute("INSERT INTO session_items(session_id,question_id,position,bucket) VALUES(?,?,?,?)",(sid,qid,pos,f"module1:{mode}"))
    return sid,len(ids),seconds


class Handler(BaseHandler):
    def do_GET(self):
        p=urlparse(self.path).path
        if p=="/health":
            return self.send_json({"status":"ok","engine":"adaptive-v4.3","curriculum":"CFA Level I 2027","goldModule":"quant-m01"})
        if p in ("/module-1","/module1"):
            return self.send_file("static/module1.html","text/html; charset=utf-8")
        if p=="/module1.js": return self.send_file("static/module1.js","text/javascript; charset=utf-8")
        if p=="/module1.css": return self.send_file("static/module1.css","text/css; charset=utf-8")
        if p=="/api/module1":
            c=conn()
            try: return self.send_json(module_snapshot(c))
            finally: c.close()
        return super().do_GET()

    def do_POST(self):
        p=urlparse(self.path).path
        if p=="/api/module1/session":
            try: data=self.read_json()
            except Exception: return self.send_json({"error":"Invalid JSON"},400)
            mode=str(data.get("mode","practice")); target=int(data.get("target") or 0)
            if mode not in ("practice","diagnostic","weak","formula","quick","exam"):
                return self.send_json({"error":"Unsupported module session"},400)
            c=conn()
            try:
                sid,n,seconds=create_module_session(c,mode,target); c.commit()
                return self.send_json({"sessionId":sid,"mode":mode,"questions":n,"timeLimitSeconds":seconds},201)
            except (ValueError,TypeError) as e:
                c.rollback(); return self.send_json({"error":str(e)},400)
            finally: c.close()
        return super().do_POST()


if __name__=="__main__":
    init_db(); seed_module1(); port=int(os.environ.get("PORT","3000"))
    print(f"CFA Recall adaptive-v4.3 · Gold Module 1 listening on :{port}")
    ThreadingHTTPServer(("0.0.0.0",port),Handler).serve_forever()
