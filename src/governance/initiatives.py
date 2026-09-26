"""工作语言、倡议草案、联合编辑与翻译稿。

关键边界：翻译稿只服务讨论；批准与发布永远针对原文修订稿。
"""

from __future__ import annotations

from datetime import datetime

from .errors import DuplicateRecord, EditConflict, NotAuthorized, ValidationError
from .models import Initiative, Revision, Translation, WorkingLanguage
from .services_base import BaseService
from .timeutil import to_utc


class InitiativeService(BaseService):
    """工作语言登记、倡议创建、修订提交与翻译稿管理。"""

    def add_working_language(self, code: str, name: str, at: datetime) -> WorkingLanguage:
        if code in self.store.languages:
            raise DuplicateRecord(f"工作语言已登记：{code}")
        language = WorkingLanguage(code, name, to_utc(at))
        self.store.languages[code] = language
        self.store.record("language_added", at, f"工作语言 {name}（{code}）启用")
        return language

    def create_initiative(
        self,
        initiative_id: str,
        title: str,
        original_language: str,
        steward_member_ids: tuple[str, ...] | list[str],
        created_by: str,
        at: datetime,
    ) -> Initiative:
        """创建倡议。原文语言必须是已登记的工作语言；创建人须为负责会员的有效代表。"""
        if initiative_id in self.store.initiatives:
            raise DuplicateRecord(f"倡议编号已存在：{initiative_id}")
        self._get(self.store.languages, original_language, "工作语言")
        if not steward_member_ids:
            raise ValidationError("倡议至少需要一个负责会员")
        for member_id in steward_member_ids:
            self._get(self.store.members, member_id, "会员")
        creator = self._require_valid_rep(created_by, at)
        if creator.member_id not in steward_member_ids:
            raise NotAuthorized("创建人必须是负责会员的有效代表")
        initiative = Initiative(
            initiative_id, title, original_language, tuple(steward_member_ids), created_by, to_utc(at)
        )
        self.store.initiatives[initiative_id] = initiative
        self.store.record("initiative_created", at, f"倡议《{title}》创建，原文语言 {original_language}")
        return initiative

    def submit_revision(
        self,
        initiative_id: str,
        revision_id: str,
        base_revision_id: str | None,
        author_ids: tuple[str, ...] | list[str],
        body: str,
        at: datetime,
    ) -> Revision:
        """提交修订稿，支持多人联合编辑。

        每位作者都须是当时可履职的有效代表；base_revision_id 必须等于
        当前最新稿，否则视为联合编辑冲突，须先合并他人修改再提交。
        """
        self._get(self.store.initiatives, initiative_id, "倡议")
        if revision_id in self.store.revisions:
            raise DuplicateRecord(f"修订编号已存在：{revision_id}")
        if not author_ids:
            raise ValidationError("修订至少需要一名作者")
        for author_id in author_ids:
            self._require_valid_rep(author_id, at)
        head = self.store.current_head(initiative_id)
        expected_base = head.id if head else None
        if base_revision_id != expected_base:
            raise EditConflict(f"基线 {base_revision_id} 不是最新修订 {expected_base}，请先合并他人修改")
        revision = Revision(
            revision_id,
            initiative_id,
            base_revision_id,
            (head.number + 1) if head else 1,
            tuple(author_ids),
            body,
            to_utc(at),
        )
        self.store.revisions[revision_id] = revision
        self.store.record(
            "revision_submitted", at, f"倡议 {initiative_id} 第 {revision.number} 稿由 {len(author_ids)} 人联合提交"
        )
        return revision

    def add_translation(
        self,
        translation_id: str,
        revision_id: str,
        language: str,
        body: str,
        translator: str,
        at: datetime,
    ) -> Translation:
        """登记翻译稿。翻译稿只服务讨论，不进入批准与发布流程。"""
        if translation_id in self.store.translations:
            raise DuplicateRecord(f"翻译稿编号已存在：{translation_id}")
        revision = self._get(self.store.revisions, revision_id, "修订稿")
        self._get(self.store.languages, language, "工作语言")
        initiative = self.store.initiatives[revision.initiative_id]
        if language == initiative.original_language:
            raise ValidationError("翻译稿语言不能就是原文语言")
        translation = Translation(translation_id, revision_id, language, body, translator, to_utc(at))
        self.store.translations[translation_id] = translation
        self.store.record("translation_added", at, f"修订稿 {revision_id} 的 {language} 翻译稿登记，仅供讨论")
        return translation
