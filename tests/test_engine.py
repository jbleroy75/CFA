import unittest
from learning_engine import allocate_mix, evidence_weight, mastery_probability, recommended_daily_questions, update_srs

class EngineTests(unittest.TestCase):
    def test_mix_exact_total(self):
        self.assertEqual(sum(allocate_mix(30).values()), 30)

    def test_guessed_correct_returns_soon(self):
        _, interval, _, _ = update_srs(2.5, 10, 3, True, "guessed")
        self.assertLessEqual(interval, 3)

    def test_known_correct_adds_more_evidence_than_guess(self):
        known = evidence_weight(True, "knew", 2, 30000)[0]
        guess = evidence_weight(True, "guessed", 2, 30000)[0]
        self.assertGreater(known, guess)

    def test_mastery_probability(self):
        self.assertAlmostEqual(mastery_probability(3, 1), 0.75)

    def test_exam_proximity_increases_load(self):
        self.assertGreaterEqual(recommended_daily_questions("2026-08-15", 30), 55)

if __name__ == '__main__': unittest.main()
