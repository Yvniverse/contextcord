import hashlib
import json
import unittest

from contextcord.continuity import pack_continuity, relative_source_path, revalidate_observations


class ContinuityTests(unittest.TestCase):
    digest = hashlib.sha256(b"public source fixture").hexdigest()

    def record(self, ident="fact-1", **extra):
        return {"memory_id": ident, "summary": "A public parser fact", "kind": "fact", "freshness": "CURRENT",
                "dependencies": [{"path": "src/parser.py", "sha256": self.digest}], **extra}

    def test_exact_source_identity_is_not_a_check_success_claim(self):
        result = revalidate_observations([self.record(kind="check")], {"src/parser.py": self.digest})
        self.assertEqual(result["current_count"], 1)
        self.assertEqual(result["records"][0]["qualification"], "SOURCE_UNCHANGED")
        self.assertNotIn("official_success", result)

    def test_changed_missing_unbound_and_stated_stale_never_upgrade(self):
        for record, snapshot in [(self.record(), {"src/parser.py": "b" * 64}), (self.record(), {}),
                                 (self.record(dependencies=[]), {}), (self.record(freshness="STALE"), {"src/parser.py": self.digest})]:
            result = revalidate_observations([record], snapshot)
            self.assertEqual(result["current_count"], 0)
            self.assertEqual(pack_continuity(result, ["fact-1"])["selected"], [])

    def test_invalid_unknown_freshness_and_duplicate_identity_fail_closed(self):
        with self.assertRaises(ValueError):
            revalidate_observations([self.record(freshness="PASS")], {})
        with self.assertRaises(ValueError):
            revalidate_observations([self.record(), self.record()], {})

    def test_absolute_traversal_control_secret_and_ambiguous_paths_rejected(self):
        for path in (chr(67) + ":/outside.txt", "/" + "app/src/a.py", "../a.py", "src/../a.py", ".codex/auth.json", ".env",
                     "src/key.pem", "src\\a.py", "src//a.py", "./src/a.py", ".contextcord-eval/state.json"):
            with self.subTest(path=path), self.assertRaises(ValueError):
                relative_source_path(path)

    def test_advisory_rank_cannot_select_stale_or_unknown(self):
        result = revalidate_observations([self.record(), self.record("old", freshness="STALE")], {"src/parser.py": self.digest})
        self.assertEqual([r["memory_id"] for r in pack_continuity(result, ["old", "fact-1"])["selected"]], ["fact-1"])
        for ids in (["missing"], ["fact-1", "fact-1"]):
            with self.assertRaises(ValueError):
                pack_continuity(result, ids)

    def test_action_and_risk_preserved_with_same_budget_for_any_ranker(self):
        rows = [self.record("fact"), self.record("risk", kind="risk"), self.record("action", kind="next_action")]
        result = revalidate_observations(rows, {"src/parser.py": self.digest})
        packed = pack_continuity(result, ["fact", "risk", "action"], max_records=2)
        self.assertEqual([r["memory_id"] for r in packed["selected"]], ["action", "risk"])

    def test_actual_serialization_budget_and_no_mutation(self):
        row = self.record(summary="\u8bc1\u636e" * 300)
        result = revalidate_observations([row], {"src/parser.py": self.digest})
        before = json.dumps(result, sort_keys=True)
        packed = pack_continuity(result, ["fact-1"], budget_tokens=300)
        serialized = json.dumps(packed, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        self.assertLessEqual((len(serialized.encode()) + 3) // 4, 300)
        self.assertEqual(before, json.dumps(result, sort_keys=True))

    def test_bad_dependency_is_rejected_without_echoing_payload(self):
        with self.assertRaisesRegex(ValueError, "continuity_dependency_shape_invalid"):
            revalidate_observations([self.record(dependencies=[{"path": "src/parser.py", "sha256": self.digest, "unexpected": "fixture"}])], {})


if __name__ == "__main__":
    unittest.main()
