"""倡议草案、多人联合编辑与翻译稿。"""

import unittest
from datetime import timedelta

from src.governance import EditConflict, InvalidRepresentative, NotAuthorized, NotFound, ValidationError
from src.governance.scenario import EPOCH, YEAR, build_basic_service

DAY = timedelta(days=1)


class InitiativeTest(unittest.TestCase):
    def setUp(self):
        self.service = build_basic_service()

    def make_initiative(self):
        self.service.create_initiative("init-1", "联合项目", "zh", ("m-east", "m-west"), "r-east", EPOCH + DAY)

    def test_create_initiative_checks_language_and_steward(self):
        with self.assertRaises(NotFound):
            self.service.create_initiative("init-x", "未知语言", "es", ("m-east",), "r-east", EPOCH + DAY)
        with self.assertRaises(NotAuthorized):
            self.service.create_initiative("init-y", "越权创建", "zh", ("m-east",), "r-west", EPOCH + DAY)

    def test_joint_revision_by_multiple_members(self):
        self.make_initiative()
        revision = self.service.submit_revision(
            "init-1", "rev-1", None, ("r-east", "r-west", "r-north"), "三家联合起草", EPOCH + 2 * DAY
        )
        self.assertEqual(revision.number, 1)
        self.assertEqual(len(revision.authors), 3)

    def test_concurrent_edit_conflict_requires_rebase(self):
        self.make_initiative()
        self.service.submit_revision("init-1", "rev-1", None, ("r-east",), "初稿", EPOCH + 2 * DAY)
        # 另一位编辑仍基于空白基线提交 → 冲突。
        with self.assertRaises(EditConflict):
            self.service.submit_revision("init-1", "rev-2", None, ("r-west",), "并行修改", EPOCH + 3 * DAY)
        # 基于最新稿重新提交 → 接受。
        revision = self.service.submit_revision("init-1", "rev-2", "rev-1", ("r-west",), "合并后修改", EPOCH + 3 * DAY)
        self.assertEqual(revision.number, 2)
        # 再有人拿着旧基线提交 → 仍冲突。
        with self.assertRaises(EditConflict):
            self.service.submit_revision("init-1", "rev-3", "rev-1", ("r-north",), "过期基线", EPOCH + 4 * DAY)

    def test_revision_author_must_be_valid_representative(self):
        self.make_initiative()
        # 任期一年已届满（会员状态仍正常），不能再以代表身份联合署名。
        with self.assertRaises(InvalidRepresentative):
            self.service.submit_revision("init-1", "rev-1", None, ("r-east",), "任期已结束", EPOCH + 2 * YEAR)

    def test_translation_only_in_registered_working_language(self):
        self.make_initiative()
        self.service.submit_revision("init-1", "rev-1", None, ("r-east",), "初稿", EPOCH + 2 * DAY)
        translation = self.service.add_translation("tr-1", "rev-1", "en", "Draft", "译员甲", EPOCH + 3 * DAY)
        self.assertEqual(translation.language, "en")
        with self.assertRaises(NotFound):
            self.service.add_translation("tr-2", "rev-1", "es", "Borrador", "译员乙", EPOCH + 3 * DAY)
        with self.assertRaises(ValidationError):
            self.service.add_translation("tr-3", "rev-1", "zh", "原文语言无需翻译", "译员丙", EPOCH + 3 * DAY)


if __name__ == "__main__":
    unittest.main()
