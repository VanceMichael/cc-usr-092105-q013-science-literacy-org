"""会议出席、代理出席、表决、法定人数变化与利益冲突回避。"""

import unittest
from datetime import timedelta

from src.governance import (
    ConflictOfInterestError,
    DuplicateRecord,
    DuplicateVote,
    MemberNotActive,
    NotAuthorized,
    ProxyError,
    ValidationError,
)
from src.governance.scenario import EPOCH, build_basic_service

DAY = timedelta(days=1)
HOUR = timedelta(hours=1)


class MeetingTest(unittest.TestCase):
    def setUp(self):
        self.service = build_basic_service()
        self.service.create_initiative("init-1", "联合项目", "zh", ("m-east", "m-west"), "r-east", EPOCH + DAY)
        self.service.submit_revision("init-1", "rev-1", None, ("r-east",), "初稿", EPOCH + 2 * DAY)
        self.service.schedule_meeting("mtg-1", "筹备会", EPOCH + 30 * DAY, "Asia/Shanghai", EPOCH + 3 * DAY)
        self.service.add_agenda_item("ag-1", "mtg-1", "审议初稿", EPOCH + 3 * DAY, initiative_id="init-1")

    def attend_all(self):
        for rep in ("r-east", "r-west", "r-north", "r-south"):
            self.service.record_attendance("mtg-1", rep, EPOCH + 30 * DAY)

    def open_resolution(self, resolution_id="res-1", at=None):
        return self.service.open_resolution(resolution_id, "ag-1", "通过初稿", at or (EPOCH + 30 * DAY + HOUR))

    def test_unknown_timezone_rejected(self):
        with self.assertRaises(ValidationError):
            self.service.schedule_meeting("mtg-x", "错误时区", EPOCH + 40 * DAY, "Mars/Olympus", EPOCH + 3 * DAY)

    def test_duplicate_attendance_rejected(self):
        self.service.record_attendance("mtg-1", "r-east", EPOCH + 30 * DAY)
        with self.assertRaises(DuplicateRecord):
            self.service.record_attendance("mtg-1", "r-east", EPOCH + 30 * DAY + HOUR)

    def test_proxy_attendance_counts_grantor_member(self):
        service = self.service
        service.grant_proxy("px-1", "mtg-1", "r-south", "r-north", EPOCH + 4 * DAY)
        attendance = service.record_attendance("mtg-1", "r-north", EPOCH + 30 * DAY, proxy_id="px-1")
        self.assertEqual(attendance.member_id, "m-south")
        # 被授权人还可以本机构身份另行签到。
        own = service.record_attendance("mtg-1", "r-north", EPOCH + 30 * DAY)
        self.assertEqual(own.member_id, "m-north")

    def test_proxy_attendance_requires_active_grant(self):
        service = self.service
        service.grant_proxy("px-1", "mtg-1", "r-south", "r-north", EPOCH + 4 * DAY)
        service.revoke_proxy("px-1", EPOCH + 5 * DAY)
        with self.assertRaises(ProxyError):
            service.record_attendance("mtg-1", "r-north", EPOCH + 30 * DAY, proxy_id="px-1")

    def test_suspended_member_cannot_attend(self):
        self.service.suspend_member("m-south", EPOCH + 10 * DAY, "暂停")
        with self.assertRaises(MemberNotActive):
            self.service.record_attendance("mtg-1", "r-south", EPOCH + 30 * DAY)

    def test_comment_can_reference_matching_translation(self):
        service = self.service
        service.add_translation("tr-1", "rev-1", "en", "Draft", "译员", EPOCH + 3 * DAY)
        comment = service.add_comment("cm-1", "ag-1", "r-west", "经费条款建议单列", EPOCH + 30 * DAY, translation_id="tr-1")
        self.assertEqual(comment.translation_id, "tr-1")
        # 其他倡议的翻译稿不能挂到本议程。
        service.create_initiative("init-2", "另一项目", "zh", ("m-east",), "r-east", EPOCH + 3 * DAY)
        service.submit_revision("init-2", "rev-9", None, ("r-east",), "另一稿", EPOCH + 3 * DAY)
        service.add_translation("tr-9", "rev-9", "en", "Other", "译员", EPOCH + 3 * DAY)
        with self.assertRaises(ValidationError):
            service.add_comment("cm-2", "ag-1", "r-west", "张冠李戴", EPOCH + 30 * DAY, translation_id="tr-9")

    def test_resolution_adopted_with_quorum_and_majority(self):
        self.attend_all()
        self.open_resolution()
        self.service.cast_vote("res-1", "r-east", "for", EPOCH + 30 * DAY + 2 * HOUR)
        self.service.cast_vote("res-1", "r-west", "for", EPOCH + 30 * DAY + 2 * HOUR)
        self.service.cast_vote("res-1", "r-north", "for", EPOCH + 30 * DAY + 2 * HOUR)
        self.service.cast_vote("res-1", "r-south", "against", EPOCH + 30 * DAY + 2 * HOUR)
        outcome = self.service.close_resolution("res-1", EPOCH + 30 * DAY + 3 * HOUR)
        self.assertTrue(outcome.quorum_met)
        self.assertTrue(outcome.adopted)
        self.assertEqual(outcome.quorum_needed, 2)

    def test_resolution_rejected_without_majority(self):
        self.attend_all()
        self.open_resolution()
        self.service.cast_vote("res-1", "r-east", "for", EPOCH + 30 * DAY + 2 * HOUR)
        self.service.cast_vote("res-1", "r-west", "against", EPOCH + 30 * DAY + 2 * HOUR)
        self.service.cast_vote("res-1", "r-north", "against", EPOCH + 30 * DAY + 2 * HOUR)
        self.service.cast_vote("res-1", "r-south", "abstain", EPOCH + 30 * DAY + 2 * HOUR)
        outcome = self.service.close_resolution("res-1", EPOCH + 30 * DAY + 3 * HOUR)
        self.assertTrue(outcome.quorum_met)
        self.assertFalse(outcome.adopted)

    def test_abstain_only_is_not_adopted(self):
        self.attend_all()
        self.open_resolution()
        self.service.cast_vote("res-1", "r-east", "abstain", EPOCH + 30 * DAY + 2 * HOUR)
        self.service.cast_vote("res-1", "r-west", "abstain", EPOCH + 30 * DAY + 2 * HOUR)
        outcome = self.service.close_resolution("res-1", EPOCH + 30 * DAY + 3 * HOUR)
        self.assertFalse(outcome.adopted)

    def test_no_quorum_when_attendance_insufficient(self):
        self.service.record_attendance("mtg-1", "r-east", EPOCH + 30 * DAY)
        self.open_resolution()
        self.service.cast_vote("res-1", "r-east", "for", EPOCH + 30 * DAY + 2 * HOUR)
        outcome = self.service.close_resolution("res-1", EPOCH + 30 * DAY + 3 * HOUR)
        self.assertFalse(outcome.quorum_met)
        self.assertFalse(outcome.adopted)

    def test_vote_guards(self):
        self.attend_all()
        self.open_resolution()
        self.service.cast_vote("res-1", "r-east", "for", EPOCH + 30 * DAY + 2 * HOUR)
        with self.assertRaises(DuplicateVote):
            self.service.cast_vote("res-1", "r-east", "against", EPOCH + 30 * DAY + 2 * HOUR)
        self.service.close_resolution("res-1", EPOCH + 30 * DAY + 3 * HOUR)
        with self.assertRaises(ValidationError):
            self.service.cast_vote("res-1", "r-west", "for", EPOCH + 30 * DAY + 4 * HOUR)

    def test_vote_requires_attendance(self):
        self.open_resolution()
        with self.assertRaises(NotAuthorized):
            self.service.cast_vote("res-1", "r-east", "for", EPOCH + 30 * DAY + 2 * HOUR)

    def test_proxy_vote_counts_for_grantor_and_blocks_double_vote(self):
        service = self.service
        service.grant_proxy("px-1", "mtg-1", "r-south", "r-north", EPOCH + 4 * DAY)
        for rep in ("r-east", "r-west", "r-north"):
            service.record_attendance("mtg-1", rep, EPOCH + 30 * DAY)
        service.record_attendance("mtg-1", "r-north", EPOCH + 30 * DAY, proxy_id="px-1")
        self.open_resolution()
        vote = service.cast_vote("res-1", "r-north", "for", EPOCH + 30 * DAY + 2 * HOUR, proxy_id="px-1")
        self.assertEqual(vote.member_id, "m-south")
        with self.assertRaises(DuplicateVote):
            service.cast_vote("res-1", "r-south", "against", EPOCH + 30 * DAY + 2 * HOUR)

    def test_suspension_after_attendance_shrinks_quorum_denominator(self):
        # 四家全部签到后，一家被暂停：出席记录保留，法定人数分母按关闭时计算。
        self.attend_all()
        self.service.suspend_member("m-south", EPOCH + 30 * DAY + HOUR, "暂停")
        self.open_resolution(at=EPOCH + 30 * DAY + 2 * HOUR)
        self.service.cast_vote("res-1", "r-east", "for", EPOCH + 30 * DAY + 2 * HOUR)
        self.service.cast_vote("res-1", "r-west", "for", EPOCH + 30 * DAY + 2 * HOUR)
        self.service.cast_vote("res-1", "r-north", "for", EPOCH + 30 * DAY + 2 * HOUR)
        outcome = self.service.close_resolution("res-1", EPOCH + 30 * DAY + 3 * HOUR)
        self.assertEqual(outcome.members_present, 4)  # 历史出席不改写
        self.assertEqual(outcome.members_eligible, 3)  # 暂停会员不计入分母
        self.assertEqual(outcome.quorum_needed, 2)
        self.assertTrue(outcome.adopted)

    def test_quorum_rule_version_locked_at_resolution_open(self):
        service = self.service
        # 新规则把法定人数提高到 3/4，自第 200 天生效。
        service.set_voting_rules("vr-2027", 3, 4, 2, 3, EPOCH + 200 * DAY)
        service.record_attendance("mtg-1", "r-east", EPOCH + 30 * DAY)
        service.record_attendance("mtg-1", "r-west", EPOCH + 30 * DAY)
        # 决议 A 在旧规则下开启，拖到新规则生效后才关闭 → 仍按 1/2。
        service.open_resolution("res-a", "ag-1", "旧规则决议", EPOCH + 100 * DAY)
        outcome_a = service.close_resolution("res-a", EPOCH + 250 * DAY)
        self.assertEqual(outcome_a.quorum_needed, 2)
        self.assertTrue(outcome_a.quorum_met)
        # 决议 B 在新规则生效后开启 → 按 3/4，两家出席不足。
        service.add_agenda_item("ag-2", "mtg-1", "另一议题", EPOCH + 3 * DAY, initiative_id="init-1")
        service.open_resolution("res-b", "ag-2", "新规则决议", EPOCH + 300 * DAY)
        outcome_b = service.close_resolution("res-b", EPOCH + 301 * DAY)
        self.assertEqual(outcome_b.quorum_needed, 3)
        self.assertFalse(outcome_b.quorum_met)

    def test_open_resolution_requires_rules(self):
        service = build_basic_service()
        service.store.voting_rules.clear()
        service.schedule_meeting("mtg-9", "无规则会议", EPOCH + 30 * DAY, "UTC", EPOCH + DAY)
        service.add_agenda_item("ag-9", "mtg-9", "议题", EPOCH + DAY)
        with self.assertRaises(ValidationError):
            service.open_resolution("res-9", "ag-9", "无规则决议", EPOCH + 2 * DAY)

    def test_declared_conflict_forces_abstention(self):
        service = self.service
        self.attend_all()
        service.declare_conflict("coi-1", "r-east", "init-1", "本机构竞标相关服务", EPOCH + 10 * DAY)
        self.open_resolution()
        with self.assertRaises(ConflictOfInterestError):
            service.cast_vote("res-1", "r-east", "for", EPOCH + 30 * DAY + 2 * HOUR)
        vote = service.cast_vote("res-1", "r-east", "abstain", EPOCH + 30 * DAY + 2 * HOUR)
        self.assertEqual(vote.choice, "abstain")
        # 声明了结后，下一项决议可以正常表决。
        service.resolve_conflict("coi-1", EPOCH + 31 * DAY)
        service.close_resolution("res-1", EPOCH + 30 * DAY + 3 * HOUR)
        self.open_resolution("res-2", at=EPOCH + 32 * DAY)
        vote2 = service.cast_vote("res-2", "r-east", "for", EPOCH + 32 * DAY + HOUR)
        self.assertEqual(vote2.choice, "for")


if __name__ == "__main__":
    unittest.main()
