"""协作治理后台。

按"世界公众科学素质组织"的议事规则维护机构会员、代表任期、工作语言、
倡议草案、资源贡献、利益冲突声明和表决规则，并保证：

- 翻译稿只服务讨论，原文批准与发布确认必须由有效代表完成；
- 跨时区换日、代理出席、会员暂停、法定人数变化、多人联合编辑
  都按发生时刻结算，不改写历史；
- 成员只看到自己的承诺与授权附件，公众入口始终指向最终生效文本。
"""

from .errors import (
    BackdatingError,
    ConflictOfInterestError,
    DuplicateRecord,
    DuplicateVote,
    EditConflict,
    GovernanceError,
    InvalidRepresentative,
    MemberNotActive,
    NotApproved,
    NotAuthorized,
    NotFound,
    ProxyError,
    TranslationNotApprovable,
    ValidationError,
)
from .service import GovernanceService
from .store import Store
from .views import audit_trail, meeting_timeline, member_portfolio, public_portal

__all__ = [
    "GovernanceService",
    "Store",
    "member_portfolio",
    "public_portal",
    "meeting_timeline",
    "audit_trail",
    "GovernanceError",
    "NotFound",
    "ValidationError",
    "DuplicateRecord",
    "BackdatingError",
    "MemberNotActive",
    "InvalidRepresentative",
    "NotAuthorized",
    "EditConflict",
    "TranslationNotApprovable",
    "NotApproved",
    "DuplicateVote",
    "ProxyError",
    "ConflictOfInterestError",
]
