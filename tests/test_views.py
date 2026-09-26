"""会员可见性、公众入口与会议时间线。"""

import unittest
from datetime import datetime, timedelta, timezone

from src.governance import audit_trail, meeting_timeline, member_portfolio, public_portal
from src.governance.scenario import EPOCH, build_basic_service

DAY = timedelta(days=1)
HOUR = timedelta(hours=1)


class VisibilityTest(unittest.TestCase):
    def setUp(self):
        service = self.service = build_basic_service()
        service.create_initiative("init-1", "联合项目", "zh", ("m-east", "m-west"), "r-east", EPOCH + DAY)
        service.submit_revision("init-1", "rev-1", None, ("r-east", "r-west"), "初稿", EPOCH + 2 * DAY)
        service.pledge_contribution("c-east", "m-east", "init-1", "funding", "经费五十万", EPOCH + 2 * DAY)
        service.pledge_contribution(
            "c-west", "m-west", "init-1", "staff", "协调员两名", EPOCH + 2 * DAY, credit_as="西岸科学联盟（协调）"
        )
        service.add_attachment("att-1", "init-1", "预算测算表", ("m-east",), "r-east", EPOCH + 2 * DAY)
        service.declare_conflict("coi-1", "r-west", "init-1", "竞标相关服务", EPOCH + 2 * DAY)
        service.approve_original("ap-1", "rev-1", "r-east", EPOCH + 3 * DAY)
        service.confirm_publication("pub-1", "project", "init-1", "r-east", EPOCH + 4 * DAY)

    def test_member_sees_only_own_commitments_and_authorized_attachments(self):
        east = member_portfolio(self.service.store, "m-east", EPOCH + 5 * DAY)
        self.assertEqual([c.id for c in east["contributions"]], ["c-east"])
        self.assertEqual([a.id for a in east["attachments"]], ["att-1"])
        self.assertEqual([s.id for s in east["signatures"]], ["ap-1", "pub-1-confirm"])
        west = member_portfolio(self.service.store, "m-west", EPOCH + 5 * DAY)
        self.assertEqual([c.id for c in west["contributions"]], ["c-west"])
        self.assertEqual(west["attachments"], [])  # 预算附件未授权给 m-west
        self.assertEqual(west["signatures"], [])
        self.assertEqual([c.id for c in west["conflicts"]], ["coi-1"])  # 本机构代表的声明

    def test_public_portal_shows_only_effective_text_and_credits(self):
        (entry,) = public_portal(self.service.store)
        self.assertEqual(
            set(entry),
            {"kind", "initiative_id", "title", "original_language", "revision_number", "body", "confirmed_at", "credits"},
        )
        self.assertEqual(entry["kind"], "project")
        self.assertEqual(entry["original_language"], "zh")
        self.assertEqual(entry["credits"], ["东方科普中心", "西岸科学联盟（协调）"])
        # 承诺明细、意见、利益冲突声明等内部材料不进入公众画面。
        self.assertNotIn("经费五十万", repr(entry))

    def test_unpublished_initiative_absent_from_portal(self):
        self.service.create_initiative("init-2", "内部项目", "zh", ("m-east",), "r-east", EPOCH + 5 * DAY)
        self.assertEqual(len(public_portal(self.service.store)), 1)


class TimelineTest(unittest.TestCase):
    def test_events_linked_by_occurrence_time(self):
        service = build_basic_service()
        service.create_initiative("init-1", "联合项目", "zh", ("m-east",), "r-east", EPOCH + DAY)
        service.schedule_meeting("mtg-1", "筹备会", EPOCH + 30 * DAY, "Asia/Shanghai", EPOCH + 2 * DAY)
        service.add_agenda_item("ag-1", "mtg-1", "审议初稿", EPOCH + 3 * DAY, initiative_id="init-1")
        service.submit_revision("init-1", "rev-1", None, ("r-east",), "初稿", EPOCH + 4 * DAY)
        # 这条意见发生在 UTC 1 月 11 日 16:30，会务时区（北京）已是 1 月 12 日。
        comment_at = datetime(2026, 1, 11, 16, 30, tzinfo=timezone.utc)
        service.add_comment("cm-1", "ag-1", "r-east", "跨日意见", comment_at)
        service.open_resolution("res-1", "ag-1", "通过初稿", EPOCH + 30 * DAY)
        service.close_resolution("res-1", EPOCH + 30 * DAY + HOUR)
        timeline = meeting_timeline(service.store, "mtg-1")
        self.assertEqual(
            [e["type"] for e in timeline],
            ["agenda", "revision", "comment", "resolution", "outcome"],
        )
        comment = timeline[2]
        self.assertEqual(comment["at_utc"].day, 11)
        self.assertEqual(comment["meeting_date"], "2026-01-12")  # 跨时区换日只影响展示
        self.assertEqual(
            [e["at_utc"] for e in timeline],
            sorted(e["at_utc"] for e in timeline),
        )

    def test_audit_trail_records_every_write(self):
        service = build_basic_service()
        service.create_initiative("init-1", "联合项目", "zh", ("m-east",), "r-east", EPOCH + DAY)
        trail = audit_trail(service.store)
        self.assertEqual([e.seq for e in trail], list(range(1, len(trail) + 1)))
        self.assertIn("initiative_created", {e.type for e in trail})


if __name__ == "__main__":
    unittest.main()
