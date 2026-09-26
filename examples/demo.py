#!/usr/bin/env python3
"""跨洲联合项目的治理流程演示。

演示世界公众科学素质组织（虚构）第一次跨洲联合项目从起草到发布的
完整链路：联合编辑、翻译稿讨论、代理出席、利益冲突回避、表决、
原文批准、发布确认，以及会员与公众各自看到的画面。

在仓库根目录运行：python3 examples/demo.py
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.governance import GovernanceService, meeting_timeline, member_portfolio, public_portal
from src.governance.scenario import EPOCH, build_basic_service


def show(title: str) -> None:
    print(f"\n=== {title} ===")


def main() -> None:
    service: GovernanceService = build_basic_service()
    day = timedelta(days=1)

    show("一、发起跨洲联合项目（中文为原文语言，东西两家机构共同负责）")
    service.create_initiative(
        "init-aurora", "极光计划：跨洲科普资源联合项目", "zh", ("m-east", "m-west"), "r-east", EPOCH + 30 * day
    )
    service.pledge_contribution("c-east", "m-east", "init-aurora", "funding", "承担秘书处经费", EPOCH + 31 * day)
    service.pledge_contribution(
        "c-west", "m-west", "init-aurora", "staff", "派出两名协调员", EPOCH + 32 * day, credit_as="西岸科学联盟（协调）"
    )
    service.add_attachment("att-1", "init-aurora", "预算测算表", ("m-east", "m-west"), "r-east", EPOCH + 32 * day)
    print("两家负责机构已登记投入承诺，预算附件仅这两家可见。")

    show("二、多人联合编辑与翻译稿讨论")
    rev1 = service.submit_revision(
        "init-aurora", "rev-1", None, ("r-east", "r-west", "r-north"), "项目章程初稿（中文）", EPOCH + 40 * day
    )
    service.add_translation("tr-1", rev1.id, "en", "Draft charter (English, for discussion)", "秘书处译员", EPOCH + 41 * day)
    print(f"第 {rev1.number} 稿由三家机构代表联合提交；英文翻译稿登记，仅供讨论。")

    show("三、跨洲会议：代理出席、利益冲突回避与表决")
    meeting_at = datetime(2026, 3, 10, 1, 0, tzinfo=timezone.utc)  # 北京 09:00，洛杉矶前一日 17:00
    service.schedule_meeting("mtg-1", "极光计划第一次筹备会", meeting_at, "Asia/Shanghai", EPOCH + 42 * day)
    service.add_agenda_item("ag-1", "mtg-1", "审议项目章程初稿", EPOCH + 42 * day, initiative_id="init-aurora")
    service.grant_proxy("px-1", "mtg-1", "r-south", "r-north", EPOCH + 43 * day)
    for rep in ("r-east", "r-west", "r-north"):
        service.record_attendance("mtg-1", rep, meeting_at)
    service.record_attendance("mtg-1", "r-north", meeting_at, proxy_id="px-1")
    print("南方机构由北方机构代表代理出席，四家会员全部到场。")
    service.add_comment("cm-1", "ag-1", "r-west", "建议经费条款单列附件", meeting_at + timedelta(hours=1), translation_id="tr-1")
    service.declare_conflict("coi-1", "r-west", "init-aurora", "本机构竞标项目印刷服务", meeting_at + timedelta(hours=1))
    service.open_resolution("res-1", "ag-1", "通过项目章程初稿并授权发布", meeting_at + timedelta(hours=2), revision_id="rev-1")
    service.cast_vote("res-1", "r-east", "for", meeting_at + timedelta(hours=2))
    service.cast_vote("res-1", "r-west", "abstain", meeting_at + timedelta(hours=2))  # 利益冲突，只能弃权
    service.cast_vote("res-1", "r-north", "for", meeting_at + timedelta(hours=2))
    service.cast_vote("res-1", "r-north", "for", meeting_at + timedelta(hours=2), proxy_id="px-1")
    outcome = service.close_resolution("res-1", meeting_at + timedelta(hours=3))
    print(f"决议{'通过' if outcome.adopted else '未通过'}：出席 {outcome.members_present}/{outcome.members_eligible}，"
          f"赞成 {outcome.votes_for} 反对 {outcome.votes_against} 弃权 {outcome.abstentions}。")

    show("四、原文批准与发布确认（翻译稿不能替代）")
    service.resolve_conflict("coi-1", meeting_at + timedelta(hours=4))  # 竞标退出，声明了结
    service.approve_original("ap-1", "rev-1", "r-east", meeting_at + timedelta(hours=4))
    service.approve_original("ap-2", "rev-1", "r-west", meeting_at + timedelta(hours=4))
    service.confirm_publication("pub-1", "project", "init-aurora", "r-east", meeting_at + timedelta(hours=5))
    print("两家负责机构的有效代表先后批准原文，秘书处确认发布。")

    show("五、会议时间线（按各自发生时刻关联，日期以会务时区显示）")
    for entry in meeting_timeline(service.store, "mtg-1"):
        print(f"  [{entry['type']:<10}] {entry['at_utc']:%Y-%m-%d %H:%MZ}（会务日期 {entry['meeting_date']}）{entry['summary']}")

    show("六、会员视角（只看自己的承诺与授权附件）")
    portfolio = member_portfolio(service.store, "m-west", meeting_at + timedelta(hours=6))
    print(f"西岸科学联盟：承诺 {len(portfolio['contributions'])} 项，授权附件 {len(portfolio['attachments'])} 件，"
          f"历史签署 {len(portfolio['signatures'])} 份，表决 {len(portfolio['votes'])} 次。")

    show("七、公众入口（始终指向最终生效文本与署名）")
    for entry in public_portal(service.store):
        print(f"  [{entry['kind']}] 《{entry['title']}》第 {entry['revision_number']} 稿"
              f"（原文语言 {entry['original_language']}），署名：{'、'.join(entry['credits'])}")


if __name__ == "__main__":
    main()
