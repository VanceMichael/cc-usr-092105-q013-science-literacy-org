"""会员状态、代表任期与代理授权。"""

import unittest
from datetime import datetime, timedelta, timezone

from src.governance import (
    BackdatingError,
    DuplicateRecord,
    InvalidRepresentative,
    MemberNotActive,
    ProxyError,
    ValidationError,
)
from src.governance.scenario import EPOCH, build_basic_service

DAY = timedelta(days=1)
BEIJING = timezone(timedelta(hours=8))


class MembershipTest(unittest.TestCase):
    def setUp(self):
        self.service = build_basic_service()

    def test_duplicate_member_rejected(self):
        with self.assertRaises(DuplicateRecord):
            self.service.register_member("m-east", "重复登记", "某国", EPOCH + DAY)

    def test_term_validity_across_timezone_day_change(self):
        # 任期到北京时间的 7 月 1 日 0 点为止。
        self.service.appoint_representative(
            "r-temp", "m-north", "临时代表", "alternate",
            datetime(2026, 1, 1, 0, 0, tzinfo=BEIJING),
            datetime(2026, 7, 1, 0, 0, tzinfo=BEIJING),
            EPOCH,
        )
        self.service.create_initiative("init-1", "联合项目", "zh", ("m-north",), "r-north", EPOCH + DAY)
        # 北京 6 月 30 日 23:30（UTC 15:30）仍在任期内，可以联合署名。
        self.service.submit_revision(
            "init-1", "rev-1", None, ("r-north", "r-temp"), "初稿",
            datetime(2026, 6, 30, 15, 30, tzinfo=timezone.utc),
        )
        # 北京 7 月 1 日 00:30（UTC 16:30）任期已结束，即使洛杉矶仍是 6 月 30 日。
        with self.assertRaises(InvalidRepresentative):
            self.service.submit_revision(
                "init-1", "rev-2", "rev-1", ("r-temp",), "第二稿",
                datetime(2026, 6, 30, 16, 30, tzinfo=timezone.utc),
            )

    def test_appoint_representative_validates_term(self):
        with self.assertRaises(ValidationError):
            self.service.appoint_representative(
                "r-bad", "m-east", "倒置任期", "primary", EPOCH + DAY, EPOCH, EPOCH
            )

    def test_suspension_blocks_new_acts_but_preserves_history(self):
        service = self.service
        service.create_initiative("init-1", "联合项目", "zh", ("m-east", "m-west"), "r-east", EPOCH + DAY)
        service.pledge_contribution("c-1", "m-west", "init-1", "funding", "经费承诺", EPOCH + 2 * DAY)
        service.submit_revision("init-1", "rev-1", None, ("r-west",), "初稿", EPOCH + 3 * DAY)
        service.suspend_member("m-west", EPOCH + 4 * DAY, "未缴会费")
        # 暂停期间：代表不能履职，也不能新增承诺。
        with self.assertRaises(MemberNotActive):
            service.submit_revision("init-1", "rev-2", "rev-1", ("r-west",), "第二稿", EPOCH + 5 * DAY)
        with self.assertRaises(MemberNotActive):
            service.pledge_contribution("c-2", "m-west", "init-1", "staff", "追加投入", EPOCH + 5 * DAY)
        # 但暂停前的承诺与修订记录原样保留。
        self.assertIn("c-1", service.store.contributions)
        self.assertIn("rev-1", service.store.revisions)
        # 恢复后可以重新履职。
        service.reinstate_member("m-west", EPOCH + 6 * DAY, "已补缴")
        service.submit_revision("init-1", "rev-2", "rev-1", ("r-west",), "第二稿", EPOCH + 7 * DAY)
        self.assertIn("rev-2", service.store.revisions)

    def test_status_change_cannot_be_backdated(self):
        service = self.service
        service.suspend_member("m-west", EPOCH + 4 * DAY, "暂停")
        with self.assertRaises(BackdatingError):
            service.reinstate_member("m-west", EPOCH + 3 * DAY, "试图倒签")
        with self.assertRaises(BackdatingError):
            service.suspend_member("m-north", EPOCH - DAY, "试图早于登记时间")

    def test_repeated_same_status_rejected(self):
        with self.assertRaises(ValidationError):
            self.service.suspend_member("m-east", EPOCH + DAY)
            self.service.suspend_member("m-east", EPOCH + 2 * DAY)

    def test_proxy_lifecycle(self):
        service = self.service
        service.schedule_meeting("mtg-1", "筹备会", EPOCH + 30 * DAY, "Asia/Shanghai", EPOCH + DAY)
        service.schedule_meeting("mtg-2", "另一场会", EPOCH + 31 * DAY, "UTC", EPOCH + DAY)
        service.grant_proxy("px-1", "mtg-1", "r-south", "r-north", EPOCH + 2 * DAY)
        # 同一授权人在同一会议只能有一份有效代理。
        with self.assertRaises(DuplicateRecord):
            service.grant_proxy("px-2", "mtg-1", "r-south", "r-east", EPOCH + 3 * DAY)
        # 不能代理给自己。
        with self.assertRaises(ProxyError):
            service.grant_proxy("px-3", "mtg-1", "r-east", "r-east", EPOCH + 3 * DAY)
        # 撤销后可以重新授权；原授权记录保留。
        service.revoke_proxy("px-1", EPOCH + 4 * DAY)
        service.grant_proxy("px-4", "mtg-1", "r-south", "r-east", EPOCH + 5 * DAY)
        self.assertIsNotNone(service.store.proxies["px-1"].revoked_at)
        self.assertIsNone(service.store.proxies["px-4"].revoked_at)


if __name__ == "__main__":
    unittest.main()
