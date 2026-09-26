"""原文批准、发布确认与公众入口指针。"""

import unittest
from datetime import timedelta

from src.governance import (
    DuplicateRecord,
    MemberNotActive,
    NotApproved,
    NotAuthorized,
    TranslationNotApprovable,
    ValidationError,
    member_portfolio,
    public_portal,
)
from src.governance.scenario import EPOCH, build_basic_service

DAY = timedelta(days=1)


class PublicationTest(unittest.TestCase):
    def setUp(self):
        self.service = build_basic_service()
        self.service.create_initiative("init-1", "联合项目", "zh", ("m-east", "m-west"), "r-east", EPOCH + DAY)
        self.service.submit_revision("init-1", "rev-1", None, ("r-east", "r-west"), "初稿", EPOCH + 2 * DAY)

    def test_publication_requires_prior_approval(self):
        with self.assertRaises(NotApproved):
            self.service.confirm_publication("pub-1", "project", "init-1", "r-east", EPOCH + 3 * DAY)

    def test_translation_cannot_be_approved(self):
        self.service.add_translation("tr-1", "rev-1", "en", "Draft", "译员", EPOCH + 3 * DAY)
        with self.assertRaises(TranslationNotApprovable):
            self.service.approve_original("ap-x", "tr-1", "r-east", EPOCH + 4 * DAY)

    def test_only_head_revision_can_be_approved(self):
        self.service.submit_revision("init-1", "rev-2", "rev-1", ("r-east",), "第二稿", EPOCH + 3 * DAY)
        with self.assertRaises(ValidationError):
            self.service.approve_original("ap-x", "rev-1", "r-east", EPOCH + 4 * DAY)

    def test_approval_requires_steward_valid_representative(self):
        with self.assertRaises(NotAuthorized):
            self.service.approve_original("ap-x", "rev-1", "r-north", EPOCH + 3 * DAY)
        self.service.suspend_member("m-west", EPOCH + 3 * DAY, "暂停")
        with self.assertRaises(MemberNotActive):
            self.service.approve_original("ap-y", "rev-1", "r-west", EPOCH + 4 * DAY)

    def test_duplicate_approval_by_same_representative_rejected(self):
        self.service.approve_original("ap-1", "rev-1", "r-east", EPOCH + 3 * DAY)
        with self.assertRaises(DuplicateRecord):
            self.service.approve_original("ap-2", "rev-1", "r-east", EPOCH + 4 * DAY)

    def test_portal_pointer_follows_latest_confirmed_revision(self):
        service = self.service
        service.approve_original("ap-1", "rev-1", "r-east", EPOCH + 3 * DAY)
        service.approve_original("ap-2", "rev-1", "r-west", EPOCH + 3 * DAY)
        service.confirm_publication("pub-1", "project", "init-1", "r-east", EPOCH + 4 * DAY)
        (entry,) = public_portal(service.store)
        self.assertEqual(entry["revision_number"], 1)
        # 草案继续修订，公众入口仍指向已生效的第一稿。
        service.submit_revision("init-1", "rev-2", "rev-1", ("r-east",), "第二稿", EPOCH + 5 * DAY)
        (entry,) = public_portal(service.store)
        self.assertEqual(entry["revision_number"], 1)
        # 第二稿批准并确认后，公众入口才前移；历史发布记录保留。
        service.approve_original("ap-3", "rev-2", "r-east", EPOCH + 6 * DAY)
        service.confirm_publication("pub-2", "project", "init-1", "r-west", EPOCH + 7 * DAY)
        (entry,) = public_portal(service.store)
        self.assertEqual(entry["revision_number"], 2)
        self.assertEqual(len(service.store.publications), 2)

    def test_unknown_publication_kind_rejected(self):
        self.service.approve_original("ap-1", "rev-1", "r-east", EPOCH + 3 * DAY)
        with self.assertRaises(ValidationError):
            self.service.confirm_publication("pub-1", "press-release", "init-1", "r-east", EPOCH + 4 * DAY)

    def test_historical_signatures_survive_term_end(self):
        service = self.service
        service.approve_original("ap-1", "rev-1", "r-east", EPOCH + 3 * DAY)
        later = EPOCH + 800 * DAY  # 代表任期早已结束
        self.assertFalse(service.store.representative_valid_at("r-east", later))
        portfolio = member_portfolio(service.store, "m-east", later)
        self.assertEqual([s.id for s in portfolio["signatures"]], ["ap-1"])
        self.assertIn("ap-1", service.store.approvals)


if __name__ == "__main__":
    unittest.main()
