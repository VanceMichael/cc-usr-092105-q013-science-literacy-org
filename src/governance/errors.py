"""治理后台的领域异常。

所有规则违例都抛出 GovernanceError 的子类，调用方可以按类捕获，
也可以统一捕获基类后读取中文消息向秘书处人员展示。
"""


class GovernanceError(Exception):
    """所有治理规则违例的基类。"""


class NotFound(GovernanceError):
    """引用的对象不存在。"""


class ValidationError(GovernanceError):
    """输入不满足结构约束。"""


class DuplicateRecord(GovernanceError):
    """同一记录被重复提交。"""


class BackdatingError(GovernanceError):
    """试图让状态变化早于既有记录生效，会改写历史。"""


class MemberNotActive(GovernanceError):
    """会员在相关时点不处于正常状态。"""


class InvalidRepresentative(GovernanceError):
    """代表在相关时点不处于有效任期。"""


class NotAuthorized(GovernanceError):
    """行为超出了代表或会员的授权范围。"""


class EditConflict(GovernanceError):
    """联合编辑的基线落后于最新修订，须先合并。"""


class TranslationNotApprovable(GovernanceError):
    """翻译稿只服务讨论，不能作为批准或发布对象。"""


class NotApproved(GovernanceError):
    """原文尚未批准，不能进入发布确认。"""


class DuplicateVote(GovernanceError):
    """同一会员对同一决议只能表决一次。"""


class ProxyError(GovernanceError):
    """代理出席或代理表决不成立。"""


class ConflictOfInterestError(GovernanceError):
    """存在未了结的利益冲突声明，相关代表只能弃权。"""
