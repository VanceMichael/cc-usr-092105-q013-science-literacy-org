"""三种视角的只读视图。

- 秘书处：直接读取 Store 全量数据与审计事件；
- 会员：member_portfolio 只回传该会员自己的承诺、代表、声明、
  授权附件与历史签署；
- 公众：public_portal 只呈现最终生效的章程、项目和成果。
"""

from __future__ import annotations

from datetime import datetime

from .errors import NotFound
from .models import Publication
from .store import Store
from .timeutil import local_date, to_utc


def member_portfolio(store: Store, member_id: str, at: datetime) -> dict:
    """会员视角：只看自己的承诺与授权附件，以及本机构的历史签署。

    历史签署不因代表任期结束或会员状态变化而消失——它们记录的是
    签署当时有效的事实。
    """
    member = store.members.get(member_id)
    if member is None:
        raise NotFound(f"会员不存在：{member_id}")
    reps = [r for r in store.representatives.values() if r.member_id == member_id]
    rep_ids = {r.id for r in reps}
    return {
        "member": member,
        "status_at": store.member_status_at(member_id, at),
        "representatives": [
            {"representative": rep, "valid_at": store.representative_valid_at(rep.id, at)} for rep in reps
        ],
        "contributions": [c for c in store.contributions.values() if c.member_id == member_id],
        "conflicts": [c for c in store.conflicts.values() if c.representative_id in rep_ids],
        "attachments": [a for a in store.attachments.values() if member_id in a.authorized_member_ids],
        "signatures": [a for a in store.approvals.values() if a.member_id == member_id],
        "votes": [v for v in store.votes.values() if v.member_id == member_id],
    }


def public_portal(store: Store) -> list[dict]:
    """公众入口：每类（章程/项目/成果）每项倡议只指向最新确认的生效稿。

    公众能看到生效文本与共同投入的署名；承诺明细、意见、利益冲突
    声明等内部材料一律不出现在这里。
    """
    latest: dict[tuple[str, str], Publication] = {}
    for publication in store.publications.values():
        key = (publication.kind, publication.initiative_id)
        current = latest.get(key)
        if current is None or to_utc(current.confirmed_at) < to_utc(publication.confirmed_at):
            latest[key] = publication
    entries = []
    for (kind, initiative_id), publication in sorted(latest.items()):
        initiative = store.initiatives[initiative_id]
        revision = store.revisions[publication.revision_id]
        credits = sorted(
            (c for c in store.contributions.values() if c.initiative_id == initiative_id),
            key=lambda c: (to_utc(c.pledged_at), c.id),
        )
        entries.append(
            {
                "kind": kind,
                "initiative_id": initiative_id,
                "title": initiative.title,
                "original_language": initiative.original_language,
                "revision_number": revision.number,
                "body": revision.body,
                "confirmed_at": publication.confirmed_at,
                "credits": [c.credit_as for c in credits],
            }
        )
    return entries


def meeting_timeline(store: Store, meeting_id: str) -> list[dict]:
    """会议时间线：议程、意见、修订、决议按各自发生时刻排序关联。

    每条记录同时给出 UTC 时刻与会务时区的本地日期，跨时区换日时
    两者可能不同，排序一律以 UTC 时刻为准。
    """
    meeting = store.meetings.get(meeting_id)
    if meeting is None:
        raise NotFound(f"会议不存在：{meeting_id}")
    items = [i for i in store.agenda_items.values() if i.meeting_id == meeting_id]
    item_ids = {i.id for i in items}
    initiative_ids = {i.initiative_id for i in items if i.initiative_id}
    entries: list[dict] = []

    def add(type_: str, at: datetime, ref: str, summary: str) -> None:
        entries.append(
            {
                "type": type_,
                "at_utc": to_utc(at),
                "meeting_date": local_date(at, meeting.timezone).isoformat(),
                "ref": ref,
                "summary": summary,
            }
        )

    for item in items:
        add("agenda", item.added_at, item.id, f"列入议程：{item.title}")
    for comment in store.comments.values():
        if comment.agenda_item_id in item_ids:
            add("comment", comment.created_at, comment.id, f"意见（{comment.author_id}）：{comment.body}")
    for revision in store.revisions.values():
        if revision.initiative_id in initiative_ids:
            add("revision", revision.created_at, revision.id, f"第 {revision.number} 稿，作者 {len(revision.authors)} 人")
    for resolution in store.resolutions.values():
        if resolution.agenda_item_id in item_ids:
            add("resolution", resolution.opened_at, resolution.id, f"决议开启：{resolution.text}")
            outcome = store.outcomes.get(resolution.id)
            if outcome is not None:
                add("outcome", outcome.closed_at, resolution.id, f"决议关闭：{'通过' if outcome.adopted else '未通过'}")
    entries.sort(key=lambda e: (e["at_utc"], e["ref"]))
    return entries


def audit_trail(store: Store) -> list:
    """秘书处审计轨迹：全部写操作事件，按发生顺序。"""
    return list(store.events)
