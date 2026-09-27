from __future__ import annotations
import unittest
from project_harness.adapters import capabilities, check_requirements
class AdapterCapabilityTests(unittest.TestCase):
    def test_capabilities_make_stop_and_file_enforcement_differences_explicit(self):
        self.assertTrue(capabilities("codex")["stop_block"]); self.assertFalse(capabilities("codex")["pretool_file_mutation"])
        self.assertTrue(capabilities("qoder")["pretool_file_mutation"]); self.assertTrue(capabilities("qoder")["stop_block"])
        self.assertFalse(capabilities("opencode")["stop_block"]); self.assertTrue(capabilities("opencode")["pretool_policy"])
        self.assertFalse(capabilities("deepseek")["stop_block"])
    def test_requirement_check_blocks_weaker_adapter(self):
        self.assertEqual(check_requirements("opencode",{"stop_block":True})["status"],"BLOCKED")
        self.assertEqual(check_requirements("qoder",{"stop_block":True,"pretool_file_mutation":True})["status"],"PASS")
if __name__=="__main__": unittest.main()
