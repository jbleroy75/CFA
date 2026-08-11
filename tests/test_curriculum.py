import json
import tempfile
import unittest
from pathlib import Path

import db
from content_import import import_bundle, normalize_topic, validate_bundle


class Curriculum2027Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        db.DB_PATH = Path(self.tmp.name) / "test.sqlite3"
        db.init_db()

    def tearDown(self):
        self.tmp.cleanup()

    def test_canonical_roots(self):
        c = db.conn()
        program = c.execute("SELECT name,source_code,year FROM curriculum_programs WHERE active=1").fetchone()
        self.assertEqual(program["name"], "CFA Program – Level I 2027")
        self.assertEqual(program["source_code"], "CFA-27-02-LI-B")
        rows = [dict(r) for r in c.execute("SELECT slug,source_course_id,expected_modules FROM topics ORDER BY sort_order")]
        self.assertEqual(sum(r["expected_modules"] for r in rows), 102)
        self.assertEqual(rows[0]["source_course_id"], 2111)
        self.assertEqual(rows[0]["expected_modules"], 11)
        self.assertEqual(rows[5]["source_course_id"], 2116)
        self.assertEqual(rows[5]["expected_modules"], 19)
        self.assertEqual(rows[-1]["source_course_id"], 2120)
        self.assertEqual(rows[-1]["expected_modules"], 10)
        names = [r[0] for r in c.execute("SELECT name FROM topics ORDER BY sort_order")]
        self.assertEqual(names, [
            "Quantitative Methods", "Economics", "Corporate Finance", "Financial Statement Analysis",
            "Equities", "Fixed Income", "Derivatives", "Alternative Investments",
            "Portfolio Construction", "Ethical and Professional Standards"
        ])
        collection = c.execute("SELECT name FROM assessment_collections WHERE slug='mock-exams'").fetchone()
        self.assertEqual(collection[0], "Mock Exams")
        c.close()

    def test_topic_aliases(self):
        self.assertEqual(normalize_topic("Corporate Finance"), "corporate")
        self.assertEqual(normalize_topic("Corporate Issuers"), "corporate")
        self.assertEqual(normalize_topic("Equities"), "equity")
        self.assertEqual(normalize_topic("Portfolio Construction"), "portfolio")

    def test_reject_other_curriculum(self):
        errors = validate_bundle({"program":{"sourceCode":"CFA-26-X"},"questions":[]})
        self.assertTrue(any("CFA-27-02-LI-B" in e for e in errors))

    def test_import_mock_as_assessment_not_topic(self):
        bundle = {
            "program":{"slug":"cfa-program-level-i-2027","sourceCode":"CFA-27-02-LI-B"},
            "version":"2027.1",
            "modules":[{"topic":"Quantitative Methods","slug":"m1","name":"Module 1"}],
            "concepts":[{"topic":"Quantitative Methods","module":"m1","slug":"c1","name":"Concept 1","prerequisites":[]}],
            "questions":[{"topic":"Quantitative Methods","module":"m1","concepts":["c1"],"prompt":"Q unique","options":["A1","B1","C1"],"correct":"A","explanation":"Because.","sourceRef":"q-1"}],
            "assessmentSets":[{"collection":"mock-exams","slug":"mock-1","name":"Mock 1","items":[{"questionSourceRef":"q-1","position":1,"section":"session-1"}]}]
        }
        result = import_bundle(bundle, "test.json")
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["importedAssessments"], 1)
        c = db.conn()
        self.assertEqual(c.execute("SELECT COUNT(*) FROM topics").fetchone()[0], 10)
        self.assertEqual(c.execute("SELECT COUNT(*) FROM assessment_sets WHERE slug='mock-1'").fetchone()[0], 1)
        self.assertEqual(c.execute("SELECT COUNT(*) FROM assessment_items").fetchone()[0], 1)
        c.close()


if __name__ == "__main__":
    unittest.main()
