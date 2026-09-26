"""会议、议程、意见、出席、决议与表决。

法定人数按"决议开启时生效的规则版本"和"关闭时状态正常的会员数"
结算：规则修订与会员暂停都只影响其生效之后的判断，不回溯。
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .errors import (
    BackdatingError,
    ConflictOfInterestError,
    DuplicateRecord,
    DuplicateVote,
    NotAuthorized,
    ProxyError,
    ValidationError,
)
from .models import AgendaItem, Attendance, Comment, Meeting, Resolution, ResolutionOutcome, Vote, VotingRules
from .services_base import BaseService
from .timeutil import to_utc

_VOTE_CHOICES = {"for", "against", "abstain"}


class MeetingService(BaseService):
    """会务与表决操作。"""

    def set_voting_rules(
        self,
        rules_id: str,
        quorum_numerator: int,
        quorum_denominator: int,
        majority_numerator: int,
        majority_denominator: int,
        effective_from: datetime,
    ) -> VotingRules:
        """登记一版表决规则，自 effective_from 起生效。"""
        for numerator, denominator, label in (
            (quorum_numerator, quorum_denominator, "法定人数"),
            (majority_numerator, majority_denominator, "表决多数"),
        ):
            if not (0 < numerator <= denominator):
                raise ValidationError(f"{label}比例无效：{numerator}/{denominator}")
        rules = VotingRules(
            rules_id,
            quorum_numerator,
            quorum_denominator,
            majority_numerator,
            majority_denominator,
            to_utc(effective_from),
        )
        self.store.voting_rules.append(rules)
        self.store.record(
            "voting_rules_set",
            effective_from,
            f"表决规则 {rules_id} 生效：法定人数 {quorum_numerator}/{quorum_denominator}，"
            f"多数 {majority_numerator}/{majority_denominator}",
        )
        return rules

    def schedule_meeting(
        self, meeting_id: str, title: str, starts_at: datetime, timezone_name: str, at: datetime
    ) -> Meeting:
        """排定会议。timezone_name 是会务时区，只影响本地日期展示。"""
        if meeting_id in self.store.meetings:
            raise DuplicateRecord(f"会议编号已存在：{meeting_id}")
        try:
            ZoneInfo(timezone_name)
        except ZoneInfoNotFoundError:
            raise ValidationError(f"未知时区：{timezone_name}") from None
        meeting = Meeting(meeting_id, title, to_utc(starts_at), timezone_name, to_utc(at))
        self.store.meetings[meeting_id] = meeting
        self.store.record("meeting_scheduled", at, f"会议《{title}》排定于 {timezone_name} 时区")
        return meeting

    def add_agenda_item(
        self, item_id: str, meeting_id: str, title: str, at: datetime, initiative_id: str | None = None
    ) -> AgendaItem:
        if item_id in self.store.agenda_items:
            raise DuplicateRecord(f"议程编号已存在：{item_id}")
        self._get(self.store.meetings, meeting_id, "会议")
        if initiative_id is not None:
            self._get(self.store.initiatives, initiative_id, "倡议")
        item = AgendaItem(item_id, meeting_id, initiative_id, title, to_utc(at))
        self.store.agenda_items[item_id] = item
        self.store.record("agenda_item_added", at, f"会议 {meeting_id} 列入议程：{title}")
        return item

    def record_attendance(
        self, meeting_id: str, representative_id: str, at: datetime, proxy_id: str | None = None
    ) -> Attendance:
        """签到。代理出席时出席资格记在被代理代表所属的会员名下。"""
        self._get(self.store.meetings, meeting_id, "会议")
        if proxy_id is None:
            rep = self._require_valid_rep(representative_id, at)
            member_id = rep.member_id
        else:
            proxy = self._get(self.store.proxies, proxy_id, "代理授权")
            if proxy.meeting_id != meeting_id:
                raise ProxyError("代理授权不属于本次会议")
            if proxy.grantee_id != representative_id:
                raise ProxyError("该代表不是此授权的被授权人")
            if not self.store.proxy_active_at(proxy, at):
                raise ProxyError("代理授权已撤销")
            grantor = self._require_valid_rep(proxy.grantor_id, at)
            self._require_valid_rep(representative_id, at)
            member_id = grantor.member_id
        if any(a.meeting_id == meeting_id and a.member_id == member_id for a in self.store.attendances):
            raise DuplicateRecord(f"会员 {member_id} 已在会议 {meeting_id} 签到")
        attendance = Attendance(meeting_id, member_id, representative_id, to_utc(at), proxy_id)
        self.store.attendances.append(attendance)
        self.store.record("attendance_recorded", at, f"会员 {member_id} 出席 {meeting_id}（代表 {representative_id}）")
        return attendance

    def add_comment(
        self,
        comment_id: str,
        agenda_item_id: str,
        author_id: str,
        body: str,
        at: datetime,
        translation_id: str | None = None,
    ) -> Comment:
        """发表意见。引用翻译稿时，翻译稿必须属于本议程讨论的倡议。"""
        if comment_id in self.store.comments:
            raise DuplicateRecord(f"意见编号已存在：{comment_id}")
        item = self._get(self.store.agenda_items, agenda_item_id, "议程")
        self._require_valid_rep(author_id, at)
        if translation_id is not None:
            translation = self._get(self.store.translations, translation_id, "翻译稿")
            revision = self.store.revisions[translation.revision_id]
            if revision.initiative_id != item.initiative_id:
                raise ValidationError("翻译稿与议程讨论的倡议不符")
        comment = Comment(comment_id, agenda_item_id, author_id, body, to_utc(at), translation_id)
        self.store.comments[comment_id] = comment
        self.store.record("comment_added", at, f"代表 {author_id} 就议程 {agenda_item_id} 发表意见")
        return comment

    def open_resolution(
        self,
        resolution_id: str,
        agenda_item_id: str,
        text: str,
        at: datetime,
        revision_id: str | None = None,
    ) -> Resolution:
        """开启决议。开启时须已有生效的表决规则，并锁定该版本用于结算。"""
        if resolution_id in self.store.resolutions:
            raise DuplicateRecord(f"决议编号已存在：{resolution_id}")
        self._get(self.store.agenda_items, agenda_item_id, "议程")
        if revision_id is not None:
            self._get(self.store.revisions, revision_id, "修订稿")
        if self.store.voting_rules_at(at) is None:
            raise ValidationError("尚无生效的表决规则，不能开启决议")
        resolution = Resolution(resolution_id, agenda_item_id, revision_id, text, to_utc(at))
        self.store.resolutions[resolution_id] = resolution
        self.store.record("resolution_opened", at, f"决议 {resolution_id} 开启：{text}")
        return resolution

    def cast_vote(
        self,
        resolution_id: str,
        representative_id: str,
        choice: str,
        at: datetime,
        proxy_id: str | None = None,
    ) -> Vote:
        """表决。一家会员一票；代理表决记在被代理会员名下。

        表决人须当时可履职、所属会员已签到；对议程关联倡议存在未了结
        利益冲突声明的代表只能投弃权票。
        """
        resolution = self._get(self.store.resolutions, resolution_id, "决议")
        if resolution_id in self.store.outcomes:
            raise ValidationError("决议已关闭，不能再表决")
        if choice not in _VOTE_CHOICES:
            raise ValidationError(f"未知表决选项：{choice}")
        item = self.store.agenda_items[resolution.agenda_item_id]
        if proxy_id is None:
            rep = self._require_valid_rep(representative_id, at)
            member_id = rep.member_id
        else:
            proxy = self._get(self.store.proxies, proxy_id, "代理授权")
            if proxy.meeting_id != item.meeting_id:
                raise ProxyError("代理授权不属于本次会议的议程")
            if proxy.grantee_id != representative_id:
                raise ProxyError("该代表不是此授权的被授权人")
            if not self.store.proxy_active_at(proxy, at):
                raise ProxyError("代理授权已撤销")
            grantor = self._require_valid_rep(proxy.grantor_id, at)
            rep = self._require_valid_rep(representative_id, at)
            member_id = grantor.member_id
        key = (resolution_id, member_id)
        if key in self.store.votes:
            raise DuplicateVote(f"会员 {member_id} 已对决议 {resolution_id} 表决")
        moment = to_utc(at)
        present = any(
            a.meeting_id == item.meeting_id and a.member_id == member_id and to_utc(a.recorded_at) <= moment
            for a in self.store.attendances
        )
        if not present:
            raise NotAuthorized(f"会员 {member_id} 未出席本次会议，不能表决")
        if choice != "abstain" and item.initiative_id and self.store.open_conflict_at(
            representative_id, item.initiative_id, at
        ):
            raise ConflictOfInterestError("该代表在此倡议上有未了结的利益冲突声明，只能弃权")
        vote = Vote(resolution_id, member_id, choice, representative_id, moment, proxy_id)
        self.store.votes[key] = vote
        self.store.record("vote_cast", at, f"会员 {member_id} 对决议 {resolution_id} 投 {choice}")
        return vote

    def close_resolution(self, resolution_id: str, at: datetime) -> ResolutionOutcome:
        """关闭决议并结算结果。

        规则版本取决议开启时生效的版本；法定人数分母取关闭时状态正常
        的会员数；已记录的出席与表决保持有效，不因事后状态变化而改写。
        """
        resolution = self._get(self.store.resolutions, resolution_id, "决议")
        if resolution_id in self.store.outcomes:
            raise DuplicateRecord("决议已关闭")
        if to_utc(at) < to_utc(resolution.opened_at):
            raise BackdatingError("关闭时间不得早于开启时间")
        item = self.store.agenda_items[resolution.agenda_item_id]
        rules = self.store.voting_rules_at(resolution.opened_at)
        if rules is None:  # open_resolution 已拦截，此处仅为防御
            raise ValidationError("决议开启时无生效表决规则")
        moment = to_utc(at)
        eligible = self.store.active_member_ids_at(moment)
        present = {
            a.member_id
            for a in self.store.attendances
            if a.meeting_id == item.meeting_id and to_utc(a.recorded_at) <= moment
        }
        quorum_needed = -(-(rules.quorum_numerator * len(eligible)) // rules.quorum_denominator)
        votes = [v for v in self.store.votes.values() if v.resolution_id == resolution_id]
        votes_for = sum(1 for v in votes if v.choice == "for")
        votes_against = sum(1 for v in votes if v.choice == "against")
        abstentions = sum(1 for v in votes if v.choice == "abstain")
        quorum_met = len(present) >= quorum_needed
        adopted = (
            quorum_met
            and votes_for > 0
            and votes_for * rules.majority_denominator
            >= rules.majority_numerator * (votes_for + votes_against)
        )
        outcome = ResolutionOutcome(
            resolution_id,
            moment,
            quorum_needed,
            len(present),
            len(eligible),
            votes_for,
            votes_against,
            abstentions,
            quorum_met,
            adopted,
        )
        self.store.outcomes[resolution_id] = outcome
        self.store.record(
            "resolution_closed",
            at,
            f"决议 {resolution_id} 关闭：{'通过' if adopted else '未通过'}"
            f"（出席 {len(present)}/{len(eligible)}，法定 {quorum_needed}，"
            f"赞成 {votes_for} 反对 {votes_against} 弃权 {abstentions}）",
        )
        return outcome
