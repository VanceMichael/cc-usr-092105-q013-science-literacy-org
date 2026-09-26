"""协作治理后台：事件溯源内核。

只读领域资料 ``src.domain`` 描述组织事实；本包在此基础上提供可运行的
登记册、会议、签署与发布流程。所有状态变化都是只追加事件，便于跨时区、
代理出席、会员暂停等并发场景下保住历史责任与签署。
"""

from .clock import MOMENT, parse_moment, now, local_date, to_text
from .store import EventStore, Event
from .state import RegistryState
from .service import GovernanceBackend, GovernanceError
from .views import member_dashboard, public_catalog

__all__ = [
    "MOMENT",
    "parse_moment",
    "now",
    "local_date",
    "to_text",
    "EventStore",
    "Event",
    "RegistryState",
    "GovernanceBackend",
    "GovernanceError",
    "member_dashboard",
    "public_catalog",
]
