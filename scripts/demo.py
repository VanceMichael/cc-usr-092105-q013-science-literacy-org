"""端到端演示：第一次跨洲联合项目的完整治理流程。

运行：``python3 scripts/demo.py``（会在 /tmp 下使用独立事件库）。

演示覆盖：
1. 三十二家创始单位、工作语言、首版表决规则就位；
2. 跨时区会议（UTC 时刻唯一），议程与意见按时间关联；
3. 翻译稿只服务讨论，章程原文经决议批准、由有效代表发布；
4. 资源贡献与授权附件只对本机构可见；
5. 会议中途暂停会员 → 法定人数基数已冻结，已承担的表决保留；
   会后依据决议恢复会籍；
6. 多人联合编辑冲突要求 rebase；
7. 代理出席与代理投票；
8. 公众入口只指向最终生效的章程、项目与成果。
"""

from __future__ import annotations

import json
import sys
import tempfile
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.governance import EventStore, GovernanceBackend, GovernanceError
from src.governance.clock import to_text, parse_moment, local_date
from src.governance.seed import bootstrap, FOUNDERS
from src.governance.views import member_dashboard, public_catalog


class Clock:
    """可手动推进的 UTC 时钟，保证演示时刻确定。"""

    def __init__(self, start: str):
        self.t = parse_moment(start)

    def __call__(self) -> datetime:
        return self.t

    def advance(self, **kw) -> None:
        from datetime import timedelta
        self.t += timedelta(**kw)


def show(title: str, value) -> None:
    print(f"\n=== {title} ===")
    if isinstance(value, (dict, list)):
        print(json.dumps(value, ensure_ascii=False, indent=2, default=str))
    else:
        print(value)


def main() -> None:
    tmp = Path(tempfile.mkdtemp(prefix="gov-demo-"))
    store = EventStore(tmp / "events.jsonl")
    clock = Clock("2026-01-01T00:00:00Z")
    gov = GovernanceBackend(store, clock=clock)

    ids = bootstrap(
        gov,
        term_start="2026-01-01T00:00:00Z",
        term_end="2028-12-31T23:59:59Z",
        rules_effective_from="2026-01-01T00:00:00Z",
    )
    rep = dict(zip([m for m, _n, _c in FOUNDERS], ids["reps"]))

    # 1) 资源贡献：中、巴、肯三家投入，附件仅自己可见 ------------------
    clock.advance(days=10)
    gov.commit_contribution(
        "C-001", "M001", "funding", "首届跨洲巡展种子资金 20 万",
        by_rep=rep["M001"], credit="华北公众科学中心",
        attachments=["auth/M001-commitment.pdf"], project_id="P-SCIENCE-TOUR")
    gov.commit_contribution(
        "C-002", "M024", "venue", "圣保罗站场馆与本地策展",
        by_rep=rep["M024"], credit="圣保罗科学传播网络",
        attachments=["auth/M024-venue.pdf"], project_id="P-SCIENCE-TOUR")
    gov.commit_contribution(
        "C-003", "M031", "outreach", "东非乡村推广志愿网络",
        by_rep=rep["M031"], credit="内罗毕乡村科学推广社",
        project_id="P-SCIENCE-TOUR")

    # 2) 章程原文 + 多语种讨论稿 ---------------------------------------
    gov.register_document("D-CHARTER", "charter", "组织章程（草案）", "zh")
    gov.propose_revision("D-CHARTER", None, "zh", "组织章程",
                         "bodies/charter-zh-r1.md", editors=[rep["M001"], rep["M017"]])
    gov.submit_translation("D-CHARTER", 1, "en", "bodies/charter-en-r1.md", rep["M015"])
    gov.submit_translation("D-CHARTER", 1, "fr", "bodies/charter-fr-r1.md", rep["M017"])

    # 联合编辑冲突：两人同时基于 r1 提交，第二个必须 rebase
    gov.propose_revision("D-CHARTER", 1, "zh", "组织章程（编辑甲修订）",
                         "bodies/charter-zh-r2-a.md", editors=[rep["M002"]])
    try:
        gov.propose_revision("D-CHARTER", 1, "zh", "组织章程（编辑乙修订）",
                             "bodies/charter-zh-r2-b.md", editors=[rep["M003"]])
    except GovernanceError as exc:
        show("联合编辑冲突被拦截", str(exc))
    gov.propose_revision("D-CHARTER", 2, "zh", "组织章程（编辑乙 rebase）",
                         "bodies/charter-zh-r3.md", editors=[rep["M003"]])

    # 3) 跨洲成立大会：UTC 22:00 = 北京次日凌晨、圣保罗同日上午 --------
    gov.schedule_meeting("MTG-1", "成立大会暨第一次跨洲联合项目会议",
                         "2026-03-02T22:00:00Z", zone="UTC")
    clock.t = parse_moment("2026-03-02T22:00:00Z")
    gov.open_meeting("MTG-1")
    show("会议召开时的当地日期",
         {"北京": str(local_date(clock(), "Asia/Shanghai")),
          "圣保罗": str(local_date(clock(), "America/Sao_Paulo")),
          "内罗毕": str(local_date(clock(), "Africa/Nairobi")),
          "UTC": to_text(clock())})

    gov.add_agenda_item("MTG-1", "ITEM-1", 1, "章程表决", "substantive",
                        subject={"kind": "document", "id": "D-CHARTER"})
    gov.post_comment("MTG-1", "ITEM-1", rep["M015"],
                     "英文版讨论稿第 4 条建议与原文对齐后再付表决。")
    gov.post_comment("MTG-1", "ITEM-1", rep["M017"],
                     "法文讨论稿不具效力，以中文原文为准，我方赞成。")

    # 4) 投票：法定人数冻结后，中途暂停会员 ----------------------------
    for mid in ["M001", "M002", "M003", "M017", "M024", "M031",
                "M015", "M004", "M019", "M027", "M022", "M012",
                "M008", "M011", "M013", "M029", "M021", "M005"]:
        gov.mark_attendance("MTG-1", rep[mid])
    gov.open_vote("MTG-1", "ITEM-1", "V-1", "批准组织章程 r3", "substantive")

    # 代理：M024 因故离会，授权 M001 的代表代投（实际由代表本人在场登记）
    gov.grant_proxy("MTG-1", rep["M024"], rep["M031"], "ITEM-1")
    gov.cast_ballot("V-1", rep["M001"], "yes")
    gov.cast_ballot("V-1", rep["M031"], "yes", on_behalf_of=rep["M024"])
    for mid in ["M002", "M003", "M017", "M015", "M004", "M019",
                "M027", "M022", "M012", "M008", "M011", "M013", "M029", "M021"]:
        gov.cast_ballot("V-1", rep[mid], "yes")
    gov.cast_ballot("V-1", rep["M005"], "no")

    # 表决进行中暂停 M005（投反对票的会员）——基数冻结，票保留
    gov.suspend_member("M005", "会费核查期间暂停表决权", by_rep=rep["M001"])
    close1 = gov.close_vote("V-1")
    show("冻结基数下的计票结果（暂停不改变本场结果）", close1.data["result"])

    gov.record_resolution("MTG-1", "ITEM-1", "V-1", "RES-1",
                          "《世界公众科学素质组织章程》中文原文 r3 予以批准。",
                          effects={"approve_document": {"doc_id": "D-CHARTER", "rev": 3}})

    # 5) 原文批准与发布确认：必须有效代表；译文通道被拒 ---------------
    gov.approve_original("D-CHARTER", 3, "RES-1", by_rep=rep["M001"])
    gov.confirm_publication("D-CHARTER", 3, by_rep=rep["M017"])

    # 6) 项目倡议与联合成果走同样流程（简列）---------------------------
    gov.add_agenda_item("MTG-1", "ITEM-2", 2, "跨洲巡展项目", "substantive",
                        subject={"kind": "project", "id": "P-SCIENCE-TOUR"})
    gov.register_document("D-PROJ", "initiative", "跨洲科学巡展倡议", "en",
                          project_id="P-SCIENCE-TOUR")
    gov.propose_revision("D-PROJ", None, "en", "Global Science Literacy Tour",
                         "bodies/project-en-r1.md", editors=[rep["M015"], rep["M024"]])
    gov.open_vote("MTG-1", "ITEM-2", "V-2", "启动跨洲巡展项目", "substantive")
    for mid in ["M001", "M017", "M015", "M024", "M031", "M019",
                "M027", "M004", "M012", "M022", "M008", "M011",
                "M029", "M002", "M003", "M013", "M021"]:
        voter = rep[mid]
        gov.cast_ballot("V-2", voter, "yes")
    gov.close_vote("V-2")
    gov.record_resolution("MTG-1", "ITEM-2", "V-2", "RES-2",
                          "启动第一次跨洲联合项目“全球科学素养巡展”。",
                          effects={"project": "P-SCIENCE-TOUR",
                                   "reinstate_member": "M005"})
    gov.approve_original("D-PROJ", 1, "RES-2", by_rep=rep["M015"])
    gov.confirm_publication("D-PROJ", 1, by_rep=rep["M024"])

    # 依据决议恢复 M005，历史投票记录仍在
    gov.reinstate_member("M005", "RES-2", by_rep=rep["M001"])

    # 联合成果：三家共同投入 → 共同署名
    gov.register_document("D-DELIV", "deliverable", "巡展联合评估报告", "en",
                          project_id="P-SCIENCE-TOUR")
    gov.propose_revision("D-DELIV", None, "en", "Joint Tour Evaluation Report",
                         "bodies/report-en-r1.md",
                         editors=[rep["M001"], rep["M024"], rep["M031"]])
    gov.add_agenda_item("MTG-1", "ITEM-3", 3, "成果发布", "substantive",
                        subject={"kind": "document", "id": "D-DELIV"})
    gov.open_vote("MTG-1", "ITEM-3", "V-3", "发布联合评估报告", "substantive")
    for mid in ["M001", "M024", "M031", "M017", "M015", "M019",
                "M027", "M004", "M012", "M022", "M008", "M011",
                "M029", "M002", "M003", "M013", "M021"]:
        gov.cast_ballot("V-3", rep[mid], "yes")
    gov.close_vote("V-3")
    gov.record_resolution("MTG-1", "ITEM-3", "V-3", "RES-3",
                          "联合评估报告英文原文 r1 批准并公开发布。",
                          effects={"approve_document": {"doc_id": "D-DELIV", "rev": 1}})
    gov.approve_original("D-DELIV", 1, "RES-3", by_rep=rep["M024"])
    gov.confirm_publication("D-DELIV", 1, by_rep=rep["M031"])
    gov.close_meeting("MTG-1")

    # 7) 视图核对 -------------------------------------------------------
    state = gov._state()
    mine = member_dashboard(state, "M024")
    show("M024 成员自助视图（只含自己的承诺与授权附件）",
         {"commitments": mine["commitments"],
          "credentials_count": len(mine["credentials"]),
          "proxies": mine["proxies"],
          "signatures": mine["signatures"]})
    other = member_dashboard(state, "M001")
    leaked = [c for c in other["commitments"] if c["contribution_id"] == "C-002"]
    show("M001 是否能看到 M024 的承诺附件", {"leak": bool(leaked)})

    show("公众入口：始终指向最终生效版本", public_catalog(state))

    # 8) 任期结束后：历史签署仍在，只是不能再做新动作 -------------------
    clock.t = parse_moment("2029-01-01T00:00:00Z")
    try:
        gov.confirm_publication("D-CHARTER", 3, by_rep=rep["M001"])
    except GovernanceError as exc:
        show("任期结束后无法再签署", str(exc))
    state_now = gov._state()
    show("任期结束后公众入口与历史签署不变",
         {"public": public_catalog(state_now)["charter"],
          "historical_approval_at": state_now.documents["D-CHARTER"]["approvals"][3]["at"].isoformat()})

    print(f"\n事件库文件：{tmp / 'events.jsonl'}")


if __name__ == "__main__":
    main()
