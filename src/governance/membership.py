"""机构会员、代表任期与代理出席。

会员状态变化只追加、不早于既有记录生效，因此任何历史时点的
签署与承诺都可以按当时状态复核，不会被事后改写。
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime

from .errors import BackdatingError, DuplicateRecord, MemberNotActive, ProxyError, ValidationError
from .models import Member, MemberStatusEvent, ProxyGrant, Representative
from .services_base import BaseService
from .timeutil import to_utc

_MEMBER_STATUSES = {"active", "suspended", "withdrawn"}
_REPRESENTATIVE_ROLES = {"primary", "alternate"}


class MembershipService(BaseService):
    """会员登记、状态变更、代表任命与代理授权。"""

    def register_member(self, member_id: str, name: str, country: str, at: datetime) -> Member:
        if member_id in self.store.members:
            raise DuplicateRecord(f"会员编号已存在：{member_id}")
        member = Member(id=member_id, name=name, country=country, joined_at=to_utc(at))
        self.store.members[member_id] = member
        self.store.member_status.append(MemberStatusEvent(member_id, "active", to_utc(at), "登记入会"))
        self.store.record("member_registered", at, f"会员 {name}（{country}）登记入会")
        return member

    def _change_member_status(self, member_id: str, status: str, at: datetime, reason: str) -> None:
        self._get(self.store.members, member_id, "会员")
        if status not in _MEMBER_STATUSES:
            raise ValidationError(f"未知会员状态：{status}")
        history = [e for e in self.store.member_status if e.member_id == member_id]
        if history and to_utc(at) < to_utc(history[-1].effective_at):
            raise BackdatingError("状态变化的生效时间不得早于既有记录，以免改写历史签署")
        current = self.store.member_status_at(member_id, at)
        if current == status:
            raise ValidationError(f"会员 {member_id} 已处于 {status} 状态")
        self.store.member_status.append(MemberStatusEvent(member_id, status, to_utc(at), reason))
        self.store.record("member_status_changed", at, f"会员 {member_id} 状态变为 {status}：{reason}")

    def suspend_member(self, member_id: str, at: datetime, reason: str = "") -> None:
        """暂停会员：此后其代表不能履职，但既有签署与承诺继续有效。"""
        self._change_member_status(member_id, "suspended", at, reason)

    def reinstate_member(self, member_id: str, at: datetime, reason: str = "") -> None:
        self._change_member_status(member_id, "active", at, reason)

    def withdraw_member(self, member_id: str, at: datetime, reason: str = "") -> None:
        self._change_member_status(member_id, "withdrawn", at, reason)

    def appoint_representative(
        self,
        representative_id: str,
        member_id: str,
        name: str,
        role: str,
        term_start: datetime,
        term_end: datetime,
        at: datetime,
    ) -> Representative:
        """任命代表。任期按带时区的半开区间解释，跨时区换日不影响判断。"""
        if representative_id in self.store.representatives:
            raise DuplicateRecord(f"代表编号已存在：{representative_id}")
        self._get(self.store.members, member_id, "会员")
        if role not in _REPRESENTATIVE_ROLES:
            raise ValidationError(f"未知代表类别：{role}")
        start, end = to_utc(term_start), to_utc(term_end)
        if not start < end:
            raise ValidationError("任期起始必须早于任期结束")
        if self.store.member_status_at(member_id, at) == "withdrawn":
            raise MemberNotActive("已退出的会员不能任命代表")
        rep = Representative(representative_id, member_id, name, role, start, end)
        self.store.representatives[representative_id] = rep
        self.store.record("representative_appointed", at, f"会员 {member_id} 任命代表 {name}（{role}）")
        return rep

    def grant_proxy(
        self, proxy_id: str, meeting_id: str, grantor_id: str, grantee_id: str, at: datetime
    ) -> ProxyGrant:
        """按会议授予代理出席权；授权人与被授权人都须当时可履职。"""
        if proxy_id in self.store.proxies:
            raise DuplicateRecord(f"代理授权编号已存在：{proxy_id}")
        self._get(self.store.meetings, meeting_id, "会议")
        if grantor_id == grantee_id:
            raise ProxyError("不能把代理权授予自己")
        self._require_valid_rep(grantor_id, at)
        self._require_valid_rep(grantee_id, at)
        for existing in self.store.proxies.values():
            if (
                existing.meeting_id == meeting_id
                and existing.grantor_id == grantor_id
                and self.store.proxy_active_at(existing, at)
            ):
                raise DuplicateRecord("该代表在此会议已有有效代理授权，请先撤销再重授")
        proxy = ProxyGrant(proxy_id, meeting_id, grantor_id, grantee_id, to_utc(at))
        self.store.proxies[proxy_id] = proxy
        self.store.record("proxy_granted", at, f"代表 {grantor_id} 就会议 {meeting_id} 授权 {grantee_id} 代理")
        return proxy

    def revoke_proxy(self, proxy_id: str, at: datetime) -> ProxyGrant:
        """撤销代理授权；原授权记录保留，只追加撤销时刻。"""
        proxy = self._get(self.store.proxies, proxy_id, "代理授权")
        if proxy.revoked_at is not None:
            raise ValidationError("代理授权已撤销")
        updated = replace(proxy, revoked_at=to_utc(at))
        self.store.proxies[proxy_id] = updated
        self.store.record("proxy_revoked", at, f"代理授权 {proxy_id} 撤销")
        return updated
