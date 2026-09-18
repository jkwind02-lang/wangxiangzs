from __future__ import annotations

import copy
import io
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from wxq_assistant.advisor import Session, analyze, prepare, validate_advice
from wxq_assistant.knowledge import FILES, Knowledge
from wxq_assistant.rules import ROOT, check_action, reminders
from wxq_assistant.state import StateError, epoch, is_fresh, snapshot_id, strict_json, utc_now, validate_state


def demo():
    return validate_state(json.loads((ROOT / "examples" / "baige_demo.json").read_text(encoding="utf-8")))


def answer(request, action=None):
    return {"snapshot_id": request["snapshot_id"], "summary": "先检查信息完整性", "next_action": action or {"type": "inspect", "uid": None, "target_uid": None},
            "reason": "资料不足时不凭空推断技能。", "alternatives": [], "risks": ["社区资料可能过期"], "unknowns": [],
            "evidence_ids": [request["evidence"][0]["source_id"]]}


class StateTests(unittest.TestCase):
    def test_valid(self):
        self.assertEqual(demo()["player"], "白歌")
    def test_unknown_energy_not_zero(self):
        s = demo(); s["energy"] = None
        self.assertIsNone(validate_state(s)["energy"])
    def test_bool_is_not_energy(self):
        s = demo(); s["energy"] = True
        with self.assertRaises(StateError): validate_state(s)
    def test_duplicate_uid(self):
        s = demo(); s["hand"][0]["uid"] = "b1"
        with self.assertRaises(StateError): validate_state(s)
    def test_incomplete_flags_required(self):
        s = demo(); del s["complete"]["shop"]
        with self.assertRaises(StateError): validate_state(s)
    def test_no_naive_timestamp(self):
        with self.assertRaises(StateError): epoch("2026-09-19T12:00:00")
    def test_reject_duplicate_json(self):
        with self.assertRaises(StateError): strict_json('{"energy":1,"energy":2}')
    def test_reject_nan(self):
        with self.assertRaises(StateError): strict_json('{"energy":NaN}')
    def test_hash_changes_on_energy(self):
        s = demo(); t = copy.deepcopy(s); t["energy"] += 1
        self.assertNotEqual(snapshot_id(s), snapshot_id(t))
    def test_hash_changes_on_match(self):
        s = demo(); t = copy.deepcopy(s); t["match_id"] = "other-match"
        self.assertNotEqual(snapshot_id(s), snapshot_id(t))
    def test_future_timestamp_not_fresh(self):
        s = demo()
        self.assertFalse(is_fresh(s, epoch(s["observed_at"]) - 10, 30))
    def test_old_timestamp_not_fresh(self):
        s = demo()
        self.assertFalse(is_fresh(s, epoch(s["observed_at"]) + 31, 30))
    def test_unknown_extra_field(self):
        s = demo(); s["imaginary_win_rate"] = 99
        with self.assertRaises(StateError): validate_state(s)
    def test_invalid_position(self):
        s = demo(); s["board"][0]["position"] = [-1, 0]
        with self.assertRaises(StateError): validate_state(s)


class RuleTests(unittest.TestCase):
    def test_threshold_reminder_conditional(self):
        text = " ".join(reminders(demo()))
        self.assertIn("若快照规则仍适用", text)
        self.assertIn("还差1次合成", text)
    def test_non_baige_not_reused(self):
        s = demo(); s["player"] = "其他棋手"
        self.assertNotIn("还差1次合成", " ".join(reminders(s)))
    def test_insufficient_energy(self):
        self.assertEqual(check_action(demo(), {"type": "buy", "uid": "s2"})["status"], "blocked")
    def test_known_price_check_is_not_full_legality(self):
        r = check_action(demo(), {"type": "buy", "uid": "s1"})
        self.assertEqual(r["status"], "conditional")
        self.assertTrue(r["unchecked"])
    def test_unknown_cost_blocks(self):
        self.assertEqual(check_action(demo(), {"type": "upgrade"})["status"], "blocked")
    def test_unknown_energy_blocks(self):
        s = demo(); s["energy"] = None
        self.assertEqual(check_action(s, {"type": "buy", "uid": "s1"})["status"], "blocked")
    def test_unknown_uid_blocks(self):
        self.assertEqual(check_action(demo(), {"type": "buy", "uid": "invented"})["status"], "blocked")
    def test_unconfirmed_blocks_sell(self):
        s = demo(); s["confirmed"] = False
        self.assertEqual(check_action(s, {"type": "sell", "uid": "b1"})["status"], "blocked")
    def test_combat_blocks_economic_action(self):
        s = demo(); s["phase"] = "combat"
        self.assertEqual(check_action(s, {"type": "buy", "uid": "s1"})["status"], "blocked")
    def test_random_cannot_name_target(self):
        self.assertEqual(check_action(demo(), {"type": "use_effect", "uid": "h1", "target_uid": "b1"})["status"], "blocked")
    def test_incomplete_random_target_set(self):
        s = demo(); s["complete"]["hand"] = False
        self.assertEqual(check_action(s, {"type": "use_effect", "uid": "h2"})["status"], "blocked")
    def test_unknown_awakened_blocks(self):
        s = demo(); s["hand"][2]["awakened"] = None
        self.assertEqual(check_action(s, {"type": "use_effect", "uid": "h2"})["status"], "blocked")
    def test_no_board_targets(self):
        s = demo(); s["board"] = []
        self.assertEqual(check_action(s, {"type": "use_effect", "uid": "h1"})["status"], "blocked")
    def test_wait_remains_information(self):
        s = demo(); s["confirmed"] = False
        self.assertEqual(check_action(s, {"type": "wait"})["status"], "informational")
    def test_effect_is_not_hero_play(self):
        self.assertEqual(check_action(demo(), {"type": "play", "uid": "h1"})["status"], "blocked")
    def test_invalid_action_field(self):
        self.assertEqual(check_action(demo(), {"type": "buy", "command": "evil"})["status"], "blocked")
    def test_list_uid_not_crash(self):
        self.assertEqual(check_action(demo(), {"type": "buy", "uid": []})["status"], "blocked")


class KnowledgeTests(unittest.TestCase):
    def make_root(self, root):
        for kind, name in FILES.items():
            rows = [{"名称": f"示例英雄{x}", "卡牌ID": str(i), "描述": "测试数据，不代表真实规则"} for i, x in enumerate("甲乙丙")] if kind == "hero" else []
            (root / name).write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
    def test_missing_files_visible(self):
        with tempfile.TemporaryDirectory() as d:
            result = Knowledge(Path(d)).for_state(demo())
            self.assertEqual(len(result["missing_files"]), 5)
            self.assertIn("hero:示例英雄甲", result["missing_names"])
    def test_full_parent_and_hash(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); self.make_root(root)
            result = Knowledge(root).for_state(demo())
            self.assertEqual(result["missing_names"], [])
            self.assertTrue(any(len(e.get("sha256", "")) == 64 for e in result["evidence"]))
    def test_type_name_collision_not_satisfied(self):
        s = demo(); s["board"][0]["name"] = "即兴创作"
        with tempfile.TemporaryDirectory() as d:
            result = Knowledge(Path(d)).for_state(s)
            self.assertIn("hero:即兴创作", result["missing_names"])
    def test_budget_omits_instead_of_truncating(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); self.make_root(root)
            result = Knowledge(root).for_state(demo(), max_characters=1)
            self.assertTrue(result["omitted_records"])
            self.assertIn("hero:示例英雄甲", result["missing_names"])


class AdviceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.kb = Knowledge(Path(self.tmp.name))
        self.request = prepare(demo(), self.kb)
    def tearDown(self): self.tmp.cleanup()
    def test_valid_informational_answer(self):
        self.assertEqual(validate_advice(answer(self.request), self.request)["status"], "conditional_advice")
    def test_fake_evidence(self):
        a = answer(self.request); a["evidence_ids"] = ["made-up"]
        with self.assertRaises(ValueError): validate_advice(a, self.request)
    def test_wrong_snapshot(self):
        a = answer(self.request); a["snapshot_id"] = "old"
        with self.assertRaises(ValueError): validate_advice(a, self.request)
    def test_unexpected_fields(self):
        a = answer(self.request); a["win_rate"] = 0.99
        with self.assertRaises(ValueError): validate_advice(a, self.request)
    def test_blocked_suggestion_replaced(self):
        a = answer(self.request, {"type": "buy", "uid": "s2"})
        a["summary"] = "立即买入，保证最优"
        r = validate_advice(a, self.request)
        self.assertEqual(r["status"], "blocked")
        self.assertEqual(r["next_action"]["type"], "inspect")
        self.assertNotIn("保证最优", json.dumps(r, ensure_ascii=False))
    def test_missing_card_text_blocks_buy(self):
        a = answer(self.request, {"type": "buy", "uid": "s1"})
        self.assertEqual(validate_advice(a, self.request)["status"], "blocked")
    def test_model_called_with_context(self):
        client = Mock(); client.complete_json.return_value = answer(self.request)
        r = analyze(demo(), client, self.kb)
        self.assertEqual(r["status"], "conditional_advice")
        self.assertIn("local_reminders", client.complete_json.call_args.args[1])
    def test_local_mode_explicit(self):
        self.assertEqual(analyze(demo(), knowledge=self.kb)["status"], "local_only")


class SessionTests(unittest.TestCase):
    def test_edit_invalidates(self):
        s = Session(); s.set_state(demo(), "replay"); t = s.begin()
        self.assertTrue(s.accepts(t)); s.invalidate(); self.assertFalse(s.accepts(t))
    def test_second_request_invalidates_first(self):
        s = Session(); s.set_state(demo(), "replay"); first = s.begin(); second = s.begin()
        self.assertFalse(s.accepts(first)); self.assertTrue(s.accepts(second))
    def test_new_match_invalidates(self):
        s = Session(); s.set_state(demo(), "replay"); t = s.begin()
        other = demo(); other["match_id"] = "new"
        s.set_state(other, "replay"); self.assertFalse(s.accepts(t))
    def test_live_rejects_old_snapshot(self):
        s = Session(); s.set_state(demo(), "live")
        with patch("wxq_assistant.advisor.time.time", return_value=epoch(demo()["observed_at"]) + 31):
            with self.assertRaises(ValueError): s.begin()
    def test_expired_response(self):
        s = Session(); s.set_state(demo(), "replay"); t = s.begin()
        with patch("wxq_assistant.advisor.time.monotonic", return_value=t.started_mono + 16):
            self.assertFalse(s.accepts(t))
    def test_replay_display_not_erased_after_publication_budget(self):
        s = Session(); s.set_state(demo(), "replay"); t = s.begin()
        with patch("wxq_assistant.advisor.time.monotonic", return_value=t.started_mono + 16):
            self.assertTrue(s.display_current(t))
    def test_live_display_expires(self):
        data = demo(); now = epoch(data["observed_at"])
        s = Session(); s.set_state(data, "live")
        with patch("wxq_assistant.advisor.time.time", return_value=now): t = s.begin()
        with patch("wxq_assistant.advisor.time.time", return_value=now + 31): self.assertFalse(s.display_current(t))

if __name__ == "__main__": unittest.main()
