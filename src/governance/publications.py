"""原文批准、发布确认与公众入口的数据来源。

批准与确认都必须由负责会员的有效代表在原文修订稿上完成；
翻译稿在数据结构上就无法进入这两条路径。
"""

from __future__ import annotations

from datetime import datetime

from .errors import DuplicateRecord, NotApproved, NotAuthorized, TranslationNotApprovable, ValidationError
from .models import Approval, Publication
from .services_base import BaseService
from .timeutil import to_utc

_PUBLICATION_KINDS = {"charter", "project", "outcome"}


class PublicationService(BaseService):
    """签署与发布操作。签署记录只增不删。"""

    def approve_original(
        self, approval_id: str, revision_id: str, representative_id: str, at: datetime
    ) -> Approval:
        """批准原文修订稿。

        只能批准当前最新稿；批准人须为负责会员当时的有效代表。
        翻译稿编号会被明确拒绝——翻译文本不能替代原文批准。
        """
        if approval_id in self.store.approvals:
            raise DuplicateRecord(f"签署编号已存在：{approval_id}")
        if revision_id in self.store.translations:
            raise TranslationNotApprovable("翻译稿只服务讨论，批准必须针对原文修订稿")
        revision = self._get(self.store.revisions, revision_id, "修订稿")
        initiative = self.store.initiatives[revision.initiative_id]
        head = self.store.current_head(initiative.id)
        if head is None or revision.id != head.id:
            raise ValidationError("只能批准当前最新修订稿")
        rep = self._require_valid_rep(representative_id, at)
        if rep.member_id not in initiative.steward_member_ids:
            raise NotAuthorized("只有负责会员的有效代表才能批准原文")
        for existing in self.store.approvals.values():
            if (
                existing.kind == "original_approval"
                and existing.revision_id == revision_id
                and existing.representative_id == representative_id
            ):
                raise DuplicateRecord("该代表已批准过此修订稿")
        approval = Approval(approval_id, "original_approval", revision_id, representative_id, rep.member_id, to_utc(at))
        self.store.approvals[approval_id] = approval
        self.store.record("original_approved", at, f"修订稿 {revision_id} 由代表 {representative_id} 批准原文")
        return approval

    def confirm_publication(
        self, publication_id: str, kind: str, initiative_id: str, representative_id: str, at: datetime
    ) -> Publication:
        """确认发布：把最近一次已批准的原文修订稿推向公众入口。

        确认人须为负责会员当时的有效代表；确认动作本身也留下签署记录。
        """
        if publication_id in self.store.publications:
            raise DuplicateRecord(f"发布编号已存在：{publication_id}")
        if kind not in _PUBLICATION_KINDS:
            raise ValidationError(f"未知发布类别：{kind}")
        initiative = self._get(self.store.initiatives, initiative_id, "倡议")
        rep = self._require_valid_rep(representative_id, at)
        if rep.member_id not in initiative.steward_member_ids:
            raise NotAuthorized("只有负责会员的有效代表才能确认发布")
        approved = self.store.latest_approved_revision(initiative_id)
        if approved is None:
            raise NotApproved("原文尚未批准，不能确认发布")
        publication = Publication(publication_id, kind, initiative_id, approved.id, representative_id, to_utc(at))
        self.store.publications[publication_id] = publication
        confirmation = Approval(
            f"{publication_id}-confirm",
            "publication_confirmation",
            approved.id,
            representative_id,
            rep.member_id,
            to_utc(at),
        )
        self.store.approvals[confirmation.id] = confirmation
        self.store.record(
            "publication_confirmed", at, f"倡议 {initiative_id} 第 {approved.number} 稿作为 {kind} 确认发布"
        )
        return publication
