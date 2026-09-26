"""治理后台的核心记录。

除特别说明外，记录一旦写入即不可变；状态变化通过追加新记录完成，
以此保住已经承担的责任和历史签署。所有时刻字段一律为带时区的
datetime，比较时归一到 UTC。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

# ---------------------------------------------------------------- 会员与代表


@dataclass(frozen=True)
class Member:
    """机构会员。"""

    id: str
    name: str
    country: str
    joined_at: datetime


@dataclass(frozen=True)
class MemberStatusEvent:
    """会员状态变化（追加式；生效时间不得早于该会员既有记录）。

    status 取值：active（正常）/ suspended（暂停）/ withdrawn（退出）。
    """

    member_id: str
    status: str
    effective_at: datetime
    reason: str = ""


@dataclass(frozen=True)
class Representative:
    """授权代表及其任期。任期按半开区间 [term_start, term_end) 解释。"""

    id: str
    member_id: str
    name: str
    role: str  # primary / alternate
    term_start: datetime
    term_end: datetime


@dataclass(frozen=True)
class ProxyGrant:
    """代理出席授权，按会议授予；撤销只追加 revoked_at，不删除原授权。"""

    id: str
    meeting_id: str
    grantor_id: str
    grantee_id: str
    created_at: datetime
    revoked_at: datetime | None = None


# ---------------------------------------------------------------- 工作语言


@dataclass(frozen=True)
class WorkingLanguage:
    """登记的工作语言。原文语言与翻译语言都必须在此登记。"""

    code: str
    name: str
    added_at: datetime


# ---------------------------------------------------------------- 倡议与文本


@dataclass(frozen=True)
class Initiative:
    """合作倡议草案。original_language 决定哪种语言文本生效。"""

    id: str
    title: str
    original_language: str
    steward_member_ids: tuple[str, ...]
    created_by: str
    created_at: datetime


@dataclass(frozen=True)
class Revision:
    """倡议修订稿。authors 支持多人联合编辑；base_revision_id 指向
    作者据以修改的上一稿，用于联合编辑的冲突检测。"""

    id: str
    initiative_id: str
    base_revision_id: str | None
    number: int
    authors: tuple[str, ...]
    body: str
    created_at: datetime


@dataclass(frozen=True)
class Translation:
    """翻译稿：只服务讨论，永远不能成为批准或发布对象。"""

    id: str
    revision_id: str
    language: str
    body: str
    translator: str
    created_at: datetime


@dataclass(frozen=True)
class Approval:
    """签署记录：原文批准或发布确认。追加保存，永不删除；
    代表任期结束或会员暂停不影响已完成的签署。"""

    id: str
    kind: str  # original_approval / publication_confirmation
    revision_id: str
    representative_id: str
    member_id: str
    signed_at: datetime


# ---------------------------------------------------------------- 会议与表决


@dataclass(frozen=True)
class Meeting:
    """会议。timezone 是会务时区，仅用于本地日期展示。"""

    id: str
    title: str
    starts_at: datetime
    timezone: str
    created_at: datetime


@dataclass(frozen=True)
class AgendaItem:
    """会议议程，可关联一项倡议。"""

    id: str
    meeting_id: str
    initiative_id: str | None
    title: str
    added_at: datetime


@dataclass(frozen=True)
class Comment:
    """会议意见，可引用翻译稿作为讨论材料。"""

    id: str
    agenda_item_id: str
    author_id: str
    body: str
    created_at: datetime
    translation_id: str | None = None


@dataclass(frozen=True)
class Attendance:
    """出席记录；via_proxy_id 非空表示代理出席，member_id 是被代理的会员。"""

    meeting_id: str
    member_id: str
    representative_id: str
    recorded_at: datetime
    via_proxy_id: str | None = None


@dataclass(frozen=True)
class VotingRules:
    """表决规则，按生效时间版本化；法定人数与多数比例均为分数。"""

    id: str
    quorum_numerator: int
    quorum_denominator: int
    majority_numerator: int
    majority_denominator: int
    effective_from: datetime


@dataclass(frozen=True)
class Resolution:
    """决议。开启时锁定当时生效的表决规则版本。"""

    id: str
    agenda_item_id: str
    revision_id: str | None
    text: str
    opened_at: datetime


@dataclass(frozen=True)
class Vote:
    """表决票。一家会员对一项决议只有一票；proxy_id 非空表示代理表决。"""

    resolution_id: str
    member_id: str
    choice: str  # for / against / abstain
    cast_by: str
    cast_at: datetime
    proxy_id: str | None = None


@dataclass(frozen=True)
class ResolutionOutcome:
    """决议结果：关闭时按开启时的规则版本与关闭时的会员状态结算，
    结算后不再改动。"""

    resolution_id: str
    closed_at: datetime
    quorum_needed: int
    members_present: int
    members_eligible: int
    votes_for: int
    votes_against: int
    abstentions: int
    quorum_met: bool
    adopted: bool


# ---------------------------------------------------------------- 承诺与声明


@dataclass(frozen=True)
class Contribution:
    """资源贡献承诺。明细只对承诺会员与秘书处可见；
    credit_as 是发布成果时的署名。"""

    id: str
    member_id: str
    initiative_id: str
    kind: str
    detail: str
    credit_as: str
    pledged_at: datetime


@dataclass(frozen=True)
class ConflictDeclaration:
    """利益冲突声明。了结只追加 resolved_at，不删除原声明。"""

    id: str
    representative_id: str
    initiative_id: str
    statement: str
    declared_at: datetime
    resolved_at: datetime | None = None


@dataclass(frozen=True)
class Attachment:
    """附件，仅列明的授权会员可见。"""

    id: str
    initiative_id: str
    name: str
    authorized_member_ids: tuple[str, ...]
    uploaded_by: str
    uploaded_at: datetime


# ---------------------------------------------------------------- 发布与审计


@dataclass(frozen=True)
class Publication:
    """发布记录：公众入口据此指向最终生效的章程、项目和成果。"""

    id: str
    kind: str  # charter / project / outcome
    initiative_id: str
    revision_id: str
    confirmed_by: str
    confirmed_at: datetime


@dataclass(frozen=True)
class Event:
    """审计事件，每次写操作追加一条。"""

    seq: int
    type: str
    at: datetime
    summary: str
