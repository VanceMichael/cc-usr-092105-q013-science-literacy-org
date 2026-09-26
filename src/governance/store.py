"""内存存储与按时刻求值的只读查询。

所有查询都接收"指定时刻"参数，保证跨时区换日、会员暂停、任期结束
等情形下的判断只取决于时刻本身，与服务器所在时区无关。生产部署时
可以用数据库实现同样的查询接口替换本模块。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from .models import (
    AgendaItem,
    Approval,
    Attachment,
    Attendance,
    Comment,
    ConflictDeclaration,
    Contribution,
    Event,
    Initiative,
    Meeting,
    Member,
    MemberStatusEvent,
    ProxyGrant,
    Publication,
    Representative,
    Resolution,
    ResolutionOutcome,
    Revision,
    Translation,
    Vote,
    VotingRules,
    WorkingLanguage,
)
from .timeutil import covers, to_utc


@dataclass
class Store:
    """全部记录的容器。签署、表决、事件等清单只增不删。"""

    members: dict[str, Member] = field(default_factory=dict)
    member_status: list[MemberStatusEvent] = field(default_factory=list)
    representatives: dict[str, Representative] = field(default_factory=dict)
    proxies: dict[str, ProxyGrant] = field(default_factory=dict)
    languages: dict[str, WorkingLanguage] = field(default_factory=dict)
    initiatives: dict[str, Initiative] = field(default_factory=dict)
    revisions: dict[str, Revision] = field(default_factory=dict)
    translations: dict[str, Translation] = field(default_factory=dict)
    approvals: dict[str, Approval] = field(default_factory=dict)
    meetings: dict[str, Meeting] = field(default_factory=dict)
    agenda_items: dict[str, AgendaItem] = field(default_factory=dict)
    comments: dict[str, Comment] = field(default_factory=dict)
    attendances: list[Attendance] = field(default_factory=list)
    voting_rules: list[VotingRules] = field(default_factory=list)
    resolutions: dict[str, Resolution] = field(default_factory=dict)
    votes: dict[tuple[str, str], Vote] = field(default_factory=dict)
    outcomes: dict[str, ResolutionOutcome] = field(default_factory=dict)
    contributions: dict[str, Contribution] = field(default_factory=dict)
    conflicts: dict[str, ConflictDeclaration] = field(default_factory=dict)
    attachments: dict[str, Attachment] = field(default_factory=dict)
    publications: dict[str, Publication] = field(default_factory=dict)
    events: list[Event] = field(default_factory=list)

    def record(self, type_: str, at: datetime, summary: str) -> None:
        """追加一条审计事件。"""
        self.events.append(Event(seq=len(self.events) + 1, type=type_, at=to_utc(at), summary=summary))

    # ------------------------------------------------------------ 时刻查询

    def member_status_at(self, member_id: str, instant: datetime) -> str:
        """会员在指定时刻的状态；无记录时视为 unregistered。"""
        moment = to_utc(instant)
        status = "unregistered"
        for event in self.member_status:
            if event.member_id == member_id and to_utc(event.effective_at) <= moment:
                status = event.status
        return status

    def representative_valid_at(self, representative_id: str, instant: datetime) -> bool:
        """代表在指定时刻是否可履职：任期覆盖该时刻且所属会员状态正常。"""
        rep = self.representatives.get(representative_id)
        if rep is None:
            return False
        return (
            covers(rep.term_start, rep.term_end, instant)
            and self.member_status_at(rep.member_id, instant) == "active"
        )

    def proxy_active_at(self, proxy: ProxyGrant, instant: datetime) -> bool:
        """代理授权在指定时刻是否有效（已授予且未撤销）。"""
        moment = to_utc(instant)
        if to_utc(proxy.created_at) > moment:
            return False
        return proxy.revoked_at is None or moment < to_utc(proxy.revoked_at)

    def current_head(self, initiative_id: str) -> Revision | None:
        """倡议的最新修订稿。"""
        revisions = [r for r in self.revisions.values() if r.initiative_id == initiative_id]
        return max(revisions, key=lambda r: r.number, default=None)

    def voting_rules_at(self, instant: datetime) -> VotingRules | None:
        """指定时刻生效的表决规则；同一生效时间以登记在后者为准。"""
        moment = to_utc(instant)
        chosen: VotingRules | None = None
        for rules in self.voting_rules:
            if to_utc(rules.effective_from) <= moment and (
                chosen is None or to_utc(rules.effective_from) >= to_utc(chosen.effective_from)
            ):
                chosen = rules
        return chosen

    def active_member_ids_at(self, instant: datetime) -> list[str]:
        """指定时刻状态正常的会员清单（法定人数的分母）。"""
        return sorted(
            member.id for member in self.members.values() if self.member_status_at(member.id, instant) == "active"
        )

    def open_conflict_at(self, representative_id: str, initiative_id: str, instant: datetime) -> bool:
        """代表在指定时刻对某倡议是否有未了结的利益冲突声明。"""
        moment = to_utc(instant)
        for declaration in self.conflicts.values():
            if declaration.representative_id != representative_id or declaration.initiative_id != initiative_id:
                continue
            if to_utc(declaration.declared_at) <= moment and (
                declaration.resolved_at is None or moment < to_utc(declaration.resolved_at)
            ):
                return True
        return False

    def latest_approved_revision(self, initiative_id: str) -> Revision | None:
        """倡议最近一次获得原文批准的修订稿。"""
        approved_ids = {a.revision_id for a in self.approvals.values() if a.kind == "original_approval"}
        revisions = [
            r for r in self.revisions.values() if r.initiative_id == initiative_id and r.id in approved_ids
        ]
        return max(revisions, key=lambda r: r.number, default=None)
