"""协作治理后台全场景测试。

覆盖：跨时区换日、代理出席、会员暂停、法定人数基数冻结与规则版本切换、
多人联合编辑冲突、利益冲突回避、原文批准与发布门禁、历史签署保全、
成员视图附件隔离、公众入口生效指针、事件幂等与并发追加。
"""

from __future__ import annotations

import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from src.governance import EventStore, GovernanceBackend, GovernanceError
from src.governance.clock import parse_moment, local_date, to_text
from src.governance.seed import bootstrap, FOUNDERS, WORKING_LANGUAGES
from src.governance.state import RegistryState
from src.governance.views import member_dashboard, public_catalog


class Clock:
    def __init__(self, start: str):
        self.t = parse_moment(start)

    def __call__(self) -> datetime:
        return self.t

    def goto(self, text: str) -> None:
        self.t = parse_moment(text)

    def advance(self, **kw) -> None:
        from datetime import timedelta
        self.t += timedelta(**kw)


class GovCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.clock = Clock("2026-01-01T00:00:00Z")
        self.store = EventStore(Path(self.tmp.name) / "events.jsonl")
        self.gov = GovernanceBackend(self.store, clock=self.clock)
        self.ids = bootstrap(
            self.gov,
            term_start="2025-01-01T00:00:00Z",
            term_end="2030-12-31T23:59:59Z",
            rules_effective_from="2026-01-01T00:00:00Z",
        )
        self.rep = {mid: f"R-{mid}" for mid in self.ids["members"]}
        self.state = self.gov._state

    def tearDown(self) -> None:
        self.tmp.cleanup()

    # -- 议事小工具 ---------------------------------------------------- #
    def charter_meeting(self, item_id: str = "ITEM-1", title: str = "章程事项"):
        self.gov.schedule_meeting("MTG", "测试大会", "2026-02-01T12:00:00Z")
        self.clock.goto("2026-02-01T12:00:00Z")
        self.gov.open_meeting("MTG")
        self.gov.add_agenda_item("MTG", item_id, 1, title, "substantive",
                                 subject={"kind": "document", "id": "DOC",
                                          "coi_scope": {"kind": "document", "id": "DOC"}})

    def yes_votes(self, vote_id: str, mids: list[str], choice: str = "yes") -> None:
        for mid in mids:
            self.gov.mark_attendance("MTG", self.rep[mid])
            self.gov.cast_ballot(vote_id, self.rep[mid], choice)

    def pass_charter_vote(self, doc_id: str = "DOC", rev: int = 1,
                          res_id: str = "RES", vote_id: str = "V",
                          item_id: str = "ITEM-1", yes_mids: list[str] | None = None) -> None:
        mids = yes_mids or self.ids["members"][:17]
        self.gov.open_vote("MTG", item_id, vote_id, f"批准 {doc_id}", "substantive")
        self.yes_votes(vote_id, mids)
        result = self.gov.close_vote(vote_id).data["result"]
        self.assertEqual(result["status"], "passed")
        self.gov.record_resolution(
            "MTG", item_id, vote_id, res_id, "决议文本",
            effects={"approve_document": {"doc_id": doc_id, "rev": rev}})


# --------------------------------------------------------------------- #
# 种子与时间
# --------------------------------------------------------------------- #
class SeedAndTimeTest(GovCase):
    def test_thirty_two_founders_in_twenty_one_countries(self):
        state = self.state()
        self.assertEqual(len(state.members), 32)
        self.assertEqual(len({m["country"] for m in state.members.values()}), 21)
        self.assertTrue(all(m["founder"] for m in state.members.values()))
        self.assertEqual(len(WORKING_LANGUAGES), 6)
        self.assertEqual(len(FOUNDERS), 32)

    def test_rules_seeded_in_force(self):
        rules = self.state().rules_in_force("assembly", self.clock())
        self.assertEqual(rules["version"], 1)
        self.assertEqual(rules["quorum"], 0.5)

    def test_seed_is_one_shot(self):
        with self.assertRaises(GovernanceError):
            self.gov.seed_founders([
                {"member_id": "X", "name": "x", "country": "c"}] * 32)

    def test_utc_normalization_and_cross_timezone_day_rollover(self):
        moment = parse_moment("2026-03-02T22:00:00+00:00")
        self.assertEqual(to_text(moment), "2026-03-02T22:00:00Z")
        # 同一 UTC 时刻：北京已换日，圣保罗还在当天，内罗毕已换日。
        self.assertEqual(str(local_date(moment, "Asia/Shanghai")), "2026-03-03")
        self.assertEqual(str(local_date(moment, "America/Sao_Paulo")), "2026-03-02")
        self.assertEqual(str(local_date(moment, "Africa/Nairobi")), "2026-03-03")
        with self.assertRaises(ValueError):
            parse_moment("2026-03-02T22:00:00")  # 不带时区拒绝

    def test_term_boundary_is_utc_and_end_exclusive(self):
        self.gov.commission_representative(
            "R-T", "M001", "临时代表",
            "2026-05-01T00:00:00Z", "2026-06-01T00:00:00Z")
        self.clock.goto("2026-04-30T23:59:59Z")
        self.assertIsNone(self.state().valid_rep("R-T", self.clock()))
        self.clock.goto("2026-05-01T00:00:00Z")
        self.assertIsNotNone(self.state().valid_rep("R-T", self.clock()))
        self.clock.goto("2026-06-01T00:00:00Z")  # 结束时刻为排他边界
        self.assertIsNone(self.state().valid_rep("R-T", self.clock()))


# --------------------------------------------------------------------- #
# 事件存储
# --------------------------------------------------------------------- #
class EventStoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = EventStore(Path(self.tmp.name) / "e.jsonl")

    def tearDown(self):
        self.tmp.cleanup()

    def test_seq_monotonic_and_idempotent_cmd(self):
        e1 = self.store.append("t", {"x": 1}, cmd="cmd-1")
        e2 = self.store.append("t", {"x": 2})
        self.assertEqual((e1.seq, e2.seq), (1, 2))
        again = self.store.append("t", {"x": 1}, cmd="cmd-1")
        self.assertEqual(again.seq, 1)
        self.assertEqual(len(self.store.replay()), 2)

    def test_concurrent_appends_serialize(self):
        import threading

        def worker(i):
            self.store.append("t", {"i": i})

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(25)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        seqs = sorted(e.seq for e in self.store.replay())
        self.assertEqual(seqs, list(range(1, 26)))


# --------------------------------------------------------------------- #
# 代表有效性与会员状态
# --------------------------------------------------------------------- #
class RepresentationTest(GovCase):
    def test_revoked_rep_invalid(self):
        self.gov.revoke_representative(self.rep["M002"], "机构改组", by_rep=self.rep["M001"])
        self.assertIsNone(self.state().valid_rep(self.rep["M002"], self.clock()))

    def test_suspended_member_rep_invalid_but_history_kept(self):
        self.charter_meeting()
        self.gov.register_document("DOC", "charter", "章程", "zh")
        self.gov.propose_revision("DOC", None, "zh", "章程 r1", "b/r1.md",
                                  editors=[self.rep["M002"]])
        self.pass_charter_vote(yes_mids=self.ids["members"][:17])
        self.gov.approve_original("DOC", 1, "RES", by_rep=self.rep["M002"])
        self.gov.confirm_publication("DOC", 1, by_rep=self.rep["M003"])

        # 暂停 M002：代表即刻失效，但批准与发布历史不动。
        self.gov.suspend_member("M002", "核查", by_rep=self.rep["M001"])
        self.assertIsNone(self.state().valid_rep(self.rep["M002"], self.clock()))
        doc = self.state().documents["DOC"]
        self.assertIn(1, doc["approvals"])
        self.assertEqual(public_catalog(self.state())["charter"]["revision"], 1)
        with self.assertRaises(GovernanceError):
            self.gov.post_comment("MTG", "ITEM-1", self.rep["M002"], "暂停后不能发言")

    def test_reinstatement_requires_matching_passed_resolution(self):
        self.gov.suspend_member("M002", "核查", by_rep=self.rep["M001"])
        with self.assertRaises(GovernanceError):
            self.gov.reinstate_member("M002", "NOPE", by_rep=self.rep["M001"])
        self.charter_meeting()
        self.gov.open_vote("MTG", "ITEM-1", "V", "x", "substantive")
        eligible = [m for m in self.ids["members"][:18] if m != "M002"]
        self.yes_votes("V", eligible[:17])
        self.gov.close_vote("V")
        self.gov.record_resolution(
            "MTG", "ITEM-1", "V", "RES-R", "恢复 M002",
            effects={"reinstate_member": "M002"})
        self.gov.reinstate_member("M002", "RES-R", by_rep=self.rep["M001"])
        self.assertEqual(self.state().members["M002"]["status"], "active")
        interval = self.state().members["M002"]["suspensions"][0]
        self.assertEqual(interval["resolution_id"], "RES-R")
        self.assertIsNotNone(interval["end"])


# --------------------------------------------------------------------- #
# 草案、翻译与联合编辑
# --------------------------------------------------------------------- #
class DocumentEditingTest(GovCase):
    def test_original_must_be_working_language(self):
        with self.assertRaises(GovernanceError):
            self.gov.register_document("D1", "charter", "章程", "de")  # 非工作语言

    def test_translation_is_discussion_only_and_cannot_be_approved(self):
        self.gov.register_document("D1", "charter", "章程", "zh")
        self.gov.propose_revision("D1", None, "zh", "章程", "b/zh-r1",
                                  editors=[self.rep["M001"]])
        self.gov.submit_translation("D1", 1, "en", "b/en-r1", self.rep["M015"])
        # 修订通道拒绝非原文语言
        with self.assertRaises(GovernanceError):
            self.gov.propose_revision("D1", 1, "en", "charter", "b/en-x",
                                      editors=[self.rep["M015"]])
        # 翻译语言本身必须是工作语言
        self.gov.archive_language("fr")
        with self.assertRaises(GovernanceError):
            self.gov.submit_translation("D1", 1, "fr", "b/fr", self.rep["M017"])
        # 译文从未成为原文修订，因此没有任何可批准对象（原批准门禁只认 r1 中文）。
        doc = self.state().documents["D1"]
        self.assertTrue(all(t["purpose"] == "discussion"
                            for ts in doc["translations"].values() for t in ts))

    def test_concurrent_edit_conflict_then_rebase(self):
        self.gov.register_document("D2", "charter", "章程", "zh")
        self.gov.propose_revision("D2", None, "zh", "r1", "b/1",
                                  editors=[self.rep["M001"]])
        self.gov.propose_revision("D2", 1, "zh", "r2-甲", "b/2",
                                  editors=[self.rep["M002"]])
        with self.assertRaises(GovernanceError):
            self.gov.propose_revision("D2", 1, "zh", "r2-乙", "b/2b",
                                      editors=[self.rep["M003"]])
        self.gov.propose_revision("D2", 2, "zh", "r3-乙rebase", "b/3",
                                  editors=[self.rep["M003"]])
        self.assertEqual(self.state().head_revision("D2")["rev"], 3)

    def test_editors_must_be_valid_reps(self):
        self.gov.register_document("D3", "initiative", "倡议", "en",
                                   project_id="P1")
        self.gov.revoke_representative(self.rep["M002"], "改组", by_rep=self.rep["M001"])
        with self.assertRaises(GovernanceError):
            self.gov.propose_revision("D3", None, "en", "r1", "b/1",
                                      editors=[self.rep["M002"]])


# --------------------------------------------------------------------- #
# 资源贡献与成员视图隔离
# --------------------------------------------------------------------- #
class ContributionViewTest(GovCase):
    def test_commitment_visibility_is_member_scoped(self):
        self.gov.commit_contribution(
            "C1", "M001", "funding", "二十万", by_rep=self.rep["M001"],
            attachments=["auth/m001.pdf"], project_id="P1")
        self.gov.commit_contribution(
            "C2", "M024", "venue", "圣保罗场馆", by_rep=self.rep["M024"],
            attachments=["auth/m024.pdf"], project_id="P1")
        with self.assertRaises(GovernanceError):
            self.gov.commit_contribution(
                "CX", "M024", "cash", "越权代登记", by_rep=self.rep["M001"])

        dash_m001 = member_dashboard(self.state(), "M001")
        ids_m001 = {c["contribution_id"] for c in dash_m001["commitments"]}
        self.assertEqual(ids_m001, {"C1"})
        self.assertEqual(dash_m001["commitments"][0]["attachments"], ["auth/m001.pdf"])
        dash_m024 = member_dashboard(self.state(), "M024")
        self.assertEqual(
            {c["contribution_id"] for c in dash_m024["commitments"]}, {"C2"})
        # 授权附件同样按机构隔离
        self.assertEqual(
            {c["credentials_ref"] for c in dash_m001["credentials"]},
            {"credentials/M001.pdf"})
        self.assertEqual(
            {c["credentials_ref"] for c in dash_m024["credentials"]},
            {"credentials/M024.pdf"})

    def test_withdrawal_keeps_history(self):
        self.gov.commit_contribution(
            "C3", "M031", "outreach", "推广网络", by_rep=self.rep["M031"])
        self.gov.withdraw_contribution("C3", by_rep=self.rep["M031"], reason="预算调整")
        c = self.state().contributions["C3"]
        self.assertEqual(c["status"], "withdrawn")
        self.assertIn("committed_at", c)  # 原始承诺仍在
        with self.assertRaises(GovernanceError):
            self.gov.withdraw_contribution("C3", by_rep=self.rep["M031"])

    def test_command_idempotency(self):
        kw = dict(by_rep=self.rep["M001"], project_id="P1")
        self.gov.commit_contribution("C4", "M001", "cash", "一", cmd="c4", **kw)
        self.gov.commit_contribution("C4", "M001", "cash", "一", cmd="c4", **kw)
        self.assertEqual(len(self.state().contributions), 1)


# --------------------------------------------------------------------- #
# 表决：法定人数、暂停、规则版本、代理、利益冲突
# --------------------------------------------------------------------- #
class VotingTest(GovCase):
    def test_quorum_failure_fails_vote(self):
        self.charter_meeting()
        self.gov.open_vote("MTG", "ITEM-1", "V", "x", "substantive")
        self.yes_votes("V", self.ids["members"][:10])  # 10/32 < 0.5
        result = self.gov.close_vote("V").data["result"]
        self.assertFalse(result["quorum_met"])
        self.assertEqual(result["status"], "failed")
        with self.assertRaises(GovernanceError):
            self.gov.record_resolution("MTG", "ITEM-1", "V", "R", "未通过不能成决议")

    def test_suspension_mid_vote_does_not_change_frozen_base(self):
        self.charter_meeting()
        self.gov.open_vote("MTG", "ITEM-1", "V", "x", "substantive")
        self.yes_votes("V", self.ids["members"][:16])
        # M017 投完后被暂停；基数与已投票都不动。
        self.gov.suspend_member("M017", "临时核查", by_rep=self.rep["M001"])
        with self.assertRaises(GovernanceError):
            self.gov.cast_ballot("V", self.rep["M017"], "yes")  # 暂停后无效代表
        # 补足一票达到 17/32
        self.gov.mark_attendance("MTG", self.rep["M018"])
        self.gov.cast_ballot("V", self.rep["M018"], "yes")
        result = self.gov.close_vote("V").data["result"]
        self.assertTrue(result["quorum_met"])
        self.assertEqual(result["base_size"], 32)
        self.assertEqual(result["members_voted"], 17)

    def test_new_vote_after_suspension_uses_new_base(self):
        self.gov.suspend_member("M017", "核查", by_rep=self.rep["M001"])
        self.charter_meeting()
        self.gov.open_vote("MTG", "ITEM-1", "V", "x", "substantive")
        base = self.gov._state().votes["V"]["rules_snapshot"]["base_members"]
        self.assertEqual(len(base), 31)
        self.assertNotIn("M017", base)

    def test_rules_version_switch_only_affects_future_votes(self):
        self.charter_meeting()
        self.gov.open_vote("MTG", "ITEM-1", "V1", "旧规则场", "substantive")
        # 会中通过新规则：30 天后生效，法定人数提高到 75%
        self.gov.enact_rules(2, 0.75, 0.5, "2026-03-01T00:00:00Z", supersedes=1)
        self.assertEqual(self.state().votes["V1"]["rules_snapshot"]["rules_version"], 1)
        self.gov.add_agenda_item("MTG", "ITEM-2", 2, "新规则场", "substantive")
        self.clock.goto("2026-03-02T12:00:00Z")
        self.gov.open_vote("MTG", "ITEM-2", "V2", "新规则场", "substantive")
        self.assertEqual(self.state().votes["V2"]["rules_snapshot"]["rules_version"], 2)
        self.assertEqual(self.state().votes["V2"]["rules_snapshot"]["quorum"], 0.75)

    def test_one_member_one_vote_duplicate_rejected(self):
        self.charter_meeting()
        self.gov.open_vote("MTG", "ITEM-1", "V", "x", "substantive")
        self.yes_votes("V", ["M001"])
        with self.assertRaises(GovernanceError):
            self.gov.cast_ballot("V", self.rep["M001"], "no")  # 改票也不行

    def test_proxy_flow_and_revocation(self):
        self.charter_meeting()
        # 代理只能授给其他机构
        self.gov.commission_representative(
            "R-M001-B", "M001", "同机构第二代表",
            "2025-01-01T00:00:00Z", "2030-12-31T23:59:59Z")
        with self.assertRaises(GovernanceError):
            self.gov.grant_proxy("MTG", self.rep["M001"], "R-M001-B")

        self.gov.mark_attendance("MTG", self.rep["M001"])
        self.gov.grant_proxy("MTG", self.rep["M024"], self.rep["M001"], "ITEM-1")
        self.gov.open_vote("MTG", "ITEM-1", "V", "x", "substantive")
        self.gov.cast_ballot("V", self.rep["M001"], "yes",
                             on_behalf_of=self.rep["M024"])
        ballot = self.state().votes["V"]["ballots"][self.rep["M001"]]
        self.assertEqual(ballot["via"], "proxy")
        self.assertEqual(ballot["source_rep"], self.rep["M024"])
        # 授权方自己不能再投
        self.gov.mark_attendance("MTG", self.rep["M024"])
        with self.assertRaises(GovernanceError):
            self.gov.cast_ballot("V", self.rep["M024"], "yes")
        # 撤销代理后，另一受托关系不能冒用
        self.gov.grant_proxy("MTG", self.rep["M009"], self.rep["M002"], "ITEM-1")
        self.gov.revoke_proxy("MTG", self.rep["M009"], self.rep["M002"], "ITEM-1")
        self.gov.mark_attendance("MTG", self.rep["M002"])
        with self.assertRaises(GovernanceError):
            self.gov.cast_ballot("V", self.rep["M002"], "yes",
                                 on_behalf_of=self.rep["M009"])
        # 不覆盖本议程项的代理不能使用
        self.gov.add_agenda_item("MTG", "ITEM-9", 9, "另一事项", "procedural")
        self.gov.grant_proxy("MTG", self.rep["M010"], self.rep["M003"], "ITEM-9")
        with self.assertRaises(GovernanceError):
            self.gov.cast_ballot("V", self.rep["M003"], "yes",
                                 on_behalf_of=self.rep["M010"])

    def test_proxy_requires_holder_attendance(self):
        self.charter_meeting()
        self.gov.grant_proxy("MTG", self.rep["M024"], self.rep["M001"], "ITEM-1")
        self.gov.open_vote("MTG", "ITEM-1", "V", "x", "substantive")
        with self.assertRaises(GovernanceError):
            self.gov.cast_ballot("V", self.rep["M031"], "yes",
                                 on_behalf_of=self.rep["M024"])  # M031 未受托
        with self.assertRaises(GovernanceError):  # M001 未登记出席
            self.gov.cast_ballot("V", self.rep["M001"], "yes",
                                 on_behalf_of=self.rep["M024"])

    def test_coi_recusal_blocks_direct_and_proxy(self):
        self.gov.declare_coi(
            "COI-1", self.rep["M009"], {"kind": "document", "id": "DOC"},
            "与成果承接方有关联")
        self.charter_meeting()
        self.gov.open_vote("MTG", "ITEM-1", "V", "x", "substantive")
        self.gov.mark_attendance("MTG", self.rep["M009"])
        with self.assertRaises(GovernanceError):
            self.gov.cast_ballot("V", self.rep["M009"], "yes")
        # 即使授权他人代投也不行
        self.gov.mark_attendance("MTG", self.rep["M010"])
        self.gov.grant_proxy("MTG", self.rep["M009"], self.rep["M010"], "ITEM-1")
        with self.assertRaises(GovernanceError):
            self.gov.cast_ballot("V", self.rep["M010"], "yes",
                                 on_behalf_of=self.rep["M009"])
        # 解除后可以投
        self.gov.resolve_coi("COI-1", by_rep=self.rep["M001"])
        self.gov.cast_ballot("V", self.rep["M009"], "yes")

    def test_comments_require_open_meeting(self):
        self.gov.schedule_meeting("M2", "未来会", "2026-09-01T00:00:00Z")
        self.gov.add_agenda_item("M2", "I", 1, "x", "procedural")  # 未开场可排议程
        with self.assertRaises(GovernanceError):
            self.gov.post_comment("M2", "I", self.rep["M001"], "不能在未开场会议发言")


# --------------------------------------------------------------------- #
# 原文批准、发布与历史签署
# --------------------------------------------------------------------- #
class ApprovalPublicationTest(GovCase):
    def _charter_r1(self):
        self.gov.register_document("DOC", "charter", "章程", "zh")
        self.gov.propose_revision("DOC", None, "zh", "章程 r1", "b/1",
                                  editors=[self.rep["M001"]])
        self.charter_meeting()
        self.pass_charter_vote()

    def test_full_approval_and_publication_gates(self):
        self._charter_r1()
        # 未批准不能发布
        with self.assertRaises(GovernanceError):
            self.gov.confirm_publication("DOC", 1, by_rep=self.rep["M003"])
        # 只有投赞成的会员能批准
        with self.assertRaises(GovernanceError):
            self.gov.approve_original("DOC", 1, "RES", by_rep=self.rep["M018"])
        self.gov.approve_original("DOC", 1, "RES", by_rep=self.rep["M001"])
        self.gov.confirm_publication("DOC", 1, by_rep=self.rep["M003"])
        # 历史签署不可重复
        with self.assertRaises(GovernanceError):
            self.gov.approve_original("DOC", 1, "RES", by_rep=self.rep["M002"])
        with self.assertRaises(GovernanceError):
            self.gov.confirm_publication("DOC", 1, by_rep=self.rep["M004"])
        catalog = public_catalog(self.state())
        self.assertEqual(catalog["charter"]["revision"], 1)
        self.assertEqual(catalog["charter"]["approved_by_resolution"], "RES")

    def test_approval_requires_passed_resolution(self):
        self.gov.register_document("DOC", "charter", "章程", "zh")
        self.gov.propose_revision("DOC", None, "zh", "r1", "b/1",
                                  editors=[self.rep["M001"]])
        with self.assertRaises(GovernanceError):
            self.gov.approve_original("DOC", 1, "GHOST", by_rep=self.rep["M001"])

    def test_new_published_revision_moves_public_pointer(self):
        self._charter_r1()
        self.gov.approve_original("DOC", 1, "RES", by_rep=self.rep["M001"])
        first_pub_at = self.clock()
        self.gov.confirm_publication("DOC", 1, by_rep=self.rep["M003"])

        # r2 走完整第二轮表决
        self.gov.propose_revision("DOC", 1, "zh", "章程 r2", "b/2",
                                  editors=[self.rep["M002"]], item_id="ITEM-1")
        self.gov.add_agenda_item("MTG", "ITEM-2", 2, "章程修订", "substantive")
        self.pass_charter_vote(rev=2, res_id="RES2", vote_id="V2", item_id="ITEM-2")
        self.gov.approve_original("DOC", 2, "RES2", by_rep=self.rep["M002"])
        self.clock.advance(days=1)
        self.gov.confirm_publication("DOC", 2, by_rep=self.rep["M004"])

        self.assertEqual(public_catalog(self.state())["charter"]["revision"], 2)
        # 历史时点视图：r2 发布前公众只能看到 r1
        past = RegistryState.replay(self.store.replay(), until=first_pub_at)
        self.assertEqual(public_catalog(past)["charter"]["revision"], 1)

    def test_signatures_survive_revoke_and_term_expiry(self):
        self._charter_r1()
        self.gov.approve_original("DOC", 1, "RES", by_rep=self.rep["M001"])
        self.gov.confirm_publication("DOC", 1, by_rep=self.rep["M003"])

        self.gov.revoke_representative(self.rep["M001"], "任期交接",
                                       by_rep=self.rep["M002"])
        self.clock.goto("2031-01-01T00:00:00Z")  # 全部代表任期结束
        approval = self.state().documents["DOC"]["approvals"][1]
        self.assertEqual(approval["by_rep"], self.rep["M001"])
        self.assertEqual(public_catalog(self.state())["charter"]["revision"], 1)
        # 不能做新动作
        with self.assertRaises(GovernanceError):
            self.gov.confirm_publication("DOC", 1, by_rep=self.rep["M003"])


# --------------------------------------------------------------------- #
# 公众入口
# --------------------------------------------------------------------- #
class PublicCatalogTest(GovCase):
    def test_drafts_and_unpublished_are_hidden(self):
        self.assertIsNone(public_catalog(self.state())["charter"])
        self.gov.register_document("DOC", "charter", "章程", "zh")
        self.gov.propose_revision("DOC", None, "zh", "r1", "b/1",
                                  editors=[self.rep["M001"]])
        # 只有草案：公众入口仍然为空
        self.assertIsNone(public_catalog(self.state())["charter"])
        self.charter_meeting()
        self.pass_charter_vote()
        self.gov.approve_original("DOC", 1, "RES", by_rep=self.rep["M001"])
        # 已批准未发布：仍不公开
        self.assertIsNone(public_catalog(self.state())["charter"])
        self.gov.confirm_publication("DOC", 1, by_rep=self.rep["M003"])
        entry = public_catalog(self.state())["charter"]
        self.assertEqual(entry["language"], "zh")  # 只暴露原文，不暴露翻译稿
        self.assertNotIn("translations", entry)

    def test_deliverable_requires_project(self):
        with self.assertRaises(GovernanceError):
            self.gov.register_document("DL", "deliverable", "报告", "en")


# --------------------------------------------------------------------- #
# 时间线
# --------------------------------------------------------------------- #
class TimelineTest(GovCase):
    def test_item_thread_orders_by_occurrence_time(self):
        self.gov.register_document("DOC", "charter", "章程", "zh")
        self.charter_meeting()
        self.gov.propose_revision("DOC", None, "zh", "r1", "b/1",
                                  editors=[self.rep["M001"]], item_id="ITEM-1")
        self.gov.post_comment("MTG", "ITEM-1", self.rep["M015"], "意见一")
        self.gov.open_vote("MTG", "ITEM-1", "V", "x", "substantive")
        self.yes_votes("V", self.ids["members"][:17])
        self.gov.close_vote("V")
        self.gov.record_resolution("MTG", "ITEM-1", "V", "RES", "决议")
        thread = self.state().item_thread("MTG", "ITEM-1")
        kinds = [t["type"] for t in thread]
        self.assertEqual(kinds, ["revision", "comment", "vote_opened",
                                 "vote_closed", "resolution"])
        # 时间严格有序
        times = [t["at"] for t in thread]
        self.assertEqual(times, sorted(times))


if __name__ == "__main__":
    unittest.main()
