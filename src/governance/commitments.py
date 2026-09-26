"""资源贡献、利益冲突声明与授权附件。

承诺与附件的可见性由视图层按会员过滤；此处只保证登记行为本身合法。
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime

from .errors import BackdatingError, DuplicateRecord, MemberNotActive, ValidationError
from .models import Attachment, ConflictDeclaration, Contribution
from .services_base import BaseService
from .timeutil import to_utc


class CommitmentService(BaseService):
    """承诺登记、利益冲突声明与附件授权。"""

    def pledge_contribution(
        self,
        contribution_id: str,
        member_id: str,
        initiative_id: str,
        kind: str,
        detail: str,
        at: datetime,
        credit_as: str | None = None,
    ) -> Contribution:
        """登记资源贡献承诺。credit_as 是发布成果时的署名，缺省用会员名。"""
        if contribution_id in self.store.contributions:
            raise DuplicateRecord(f"贡献编号已存在：{contribution_id}")
        member = self._get(self.store.members, member_id, "会员")
        self._get(self.store.initiatives, initiative_id, "倡议")
        if self.store.member_status_at(member_id, at) != "active":
            raise MemberNotActive("会员在该时点不处于正常状态，不能新增承诺")
        contribution = Contribution(
            contribution_id, member_id, initiative_id, kind, detail, credit_as or member.name, to_utc(at)
        )
        self.store.contributions[contribution_id] = contribution
        self.store.record("contribution_pledged", at, f"会员 {member_id} 承诺 {kind} 投入（倡议 {initiative_id}）")
        return contribution

    def declare_conflict(
        self, declaration_id: str, representative_id: str, initiative_id: str, statement: str, at: datetime
    ) -> ConflictDeclaration:
        """登记利益冲突声明。"""
        if declaration_id in self.store.conflicts:
            raise DuplicateRecord(f"声明编号已存在：{declaration_id}")
        self._get(self.store.representatives, representative_id, "代表")
        self._get(self.store.initiatives, initiative_id, "倡议")
        declaration = ConflictDeclaration(declaration_id, representative_id, initiative_id, statement, to_utc(at))
        self.store.conflicts[declaration_id] = declaration
        self.store.record(
            "conflict_declared", at, f"代表 {representative_id} 就倡议 {initiative_id} 声明利益冲突"
        )
        return declaration

    def resolve_conflict(self, declaration_id: str, at: datetime) -> ConflictDeclaration:
        """了结利益冲突声明；原声明保留，只追加了结时刻。"""
        declaration = self._get(self.store.conflicts, declaration_id, "利益冲突声明")
        if declaration.resolved_at is not None:
            raise ValidationError("声明已了结")
        if to_utc(at) < to_utc(declaration.declared_at):
            raise BackdatingError("了结时间不得早于声明时间")
        updated = replace(declaration, resolved_at=to_utc(at))
        self.store.conflicts[declaration_id] = updated
        self.store.record("conflict_resolved", at, f"利益冲突声明 {declaration_id} 了结")
        return updated

    def add_attachment(
        self,
        attachment_id: str,
        initiative_id: str,
        name: str,
        authorized_member_ids: tuple[str, ...] | list[str],
        uploaded_by: str,
        at: datetime,
    ) -> Attachment:
        """登记附件并限定可见会员。上传人须为有效代表。"""
        if attachment_id in self.store.attachments:
            raise DuplicateRecord(f"附件编号已存在：{attachment_id}")
        self._get(self.store.initiatives, initiative_id, "倡议")
        self._require_valid_rep(uploaded_by, at)
        if not authorized_member_ids:
            raise ValidationError("附件至少授权一家会员")
        for member_id in authorized_member_ids:
            self._get(self.store.members, member_id, "会员")
        attachment = Attachment(
            attachment_id, initiative_id, name, tuple(authorized_member_ids), uploaded_by, to_utc(at)
        )
        self.store.attachments[attachment_id] = attachment
        self.store.record(
            "attachment_added", at, f"附件《{name}》登记，授权 {len(authorized_member_ids)} 家会员可见"
        )
        return attachment
