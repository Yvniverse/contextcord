import unittest

from project_harness.bm25 import BM25Selector


class BM25SelectorTests(unittest.TestCase):
    def test_real_okapi_selection_is_deterministic(self):
        rows = [
            {"id": "a", "text": "retry resume checkpoint contract"},
            {"id": "b", "text": "unrelated interface color"},
            {"id": "c", "text": "retry retry retry"},
        ]
        first = BM25Selector().select("retry resume", rows, limit=2)
        second = BM25Selector().select("retry resume", rows, limit=2)
        self.assertEqual(first.selected_memory_ids, second.selected_memory_ids)
        self.assertEqual(first.as_dict()["selector"], "bm25")
        self.assertEqual(first.selected[0]["memory_id"], "a")
        self.assertTrue(first.candidate_pool_sha256)

    def test_ties_keep_input_order(self):
        rows = [{"id": "first", "text": "same"}, {"id": "second", "text": "same"}]
        selection = BM25Selector().select("same", rows, limit=2)
        self.assertEqual(["first", "second"], list(selection.selected_memory_ids))


if __name__ == "__main__":
    unittest.main()
