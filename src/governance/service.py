"""协作治理后台的统一入口。"""

from __future__ import annotations

from .commitments import CommitmentService
from .initiatives import InitiativeService
from .meetings import MeetingService
from .membership import MembershipService
from .publications import PublicationService


class GovernanceService(
    MembershipService,
    InitiativeService,
    MeetingService,
    CommitmentService,
    PublicationService,
):
    """面向秘书处的治理后台服务。

    所有写操作都显式接收时刻参数 at（调用方通常传当前 UTC 时间），
    判断只依赖时刻本身，与服务器所在时区无关；所有写操作都会追加
    审计事件，签署与承诺记录只增不删。
    """
