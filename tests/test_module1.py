import os
import tempfile
import unittest
from pathlib import Path

_tmp = tempfile.TemporaryDirectory()
os.environ["DB_PATH"] = str(Path(_tmp.name) / "module1.sqlite3")

import db
from module1_seed import generate_questions, seed_module1
from module_server import module_snapshot, create_module_session


class Module1Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        db.DB_PATH = Path(_tmp.name) / "module1.sqlite3"
        db.init_db(); seed_module1()

    def test_generated_bank_is_large_and_original(self):
        qs = generate_questions()
        self.assertGreaterEqual(len(qs), 90)
        self.assertEqual(len({q["prompt"] for q in qs}), len(qs))
        self.assertTrue(all(q["sourceRef"].startswith("original:m1:") for q in qs))
        self.assertTrue(all(len(q["options"]) == len(set(q["options"])) for q in qs))

    def test_module_has_eight_micro_concepts(self):
        c=db.conn()
        try:
            m=c.execute("SELECT id FROM learning_modules WHERE slug='quant-m01-returns-financial-assets'").fetchone()
            self.assertIsNotNone(m)
            n=c.execute("SELECT COUNT(*) FROM concepts WHERE module_id=?",(m[0],)).fetchone()[0]
            self.assertEqual(n,8)
        finally: c.close()

    def test_snapshot_exposes_gold_module_metrics(self):
        c=db.conn()
        try:
            snap=module_snapshot(c)
            self.assertEqual(snap["module"]["moduleNumber"],1)
            self.assertGreaterEqual(snap["stats"]["questionBank"],90)
            self.assertEqual(snap["sourceInventory"]["officialTotalQuestionCount"],34)
            self.assertEqual(snap["sourceInventory"]["practicePackIncludedCount"],7)
            self.assertFalse(snap["taxonomy"]["isOfficialLOS"])
        finally: c.close()

    def test_module_sessions_only_use_module_questions(self):
        c=db.conn()
        try:
            sid,n,_=create_module_session(c,"practice",20); c.commit()
            self.assertEqual(n,20)
            outside=c.execute('''SELECT COUNT(*) FROM session_items si JOIN questions q ON q.id=si.question_id
               JOIN learning_modules lm ON lm.id=q.module_id WHERE si.session_id=? AND lm.slug!='quant-m01-returns-financial-assets' ''',(sid,)).fetchone()[0]
            self.assertEqual(outside,0)
        finally: c.close()

    def test_module_exam_is_deferred_exam_mode(self):
        c=db.conn()
        try:
            sid,n,seconds=create_module_session(c,"exam",34); c.commit()
            s=c.execute("SELECT mode,time_limit_seconds FROM sessions WHERE id=?",(sid,)).fetchone()
            self.assertEqual(s["mode"],"exam")
            self.assertEqual(n,34)
            self.assertEqual(seconds,34*90)
        finally: c.close()


if __name__ == '__main__': unittest.main()
