"""服务基类：各业务模块共用的查找与校验。"""

from __future__ import annotations

from datetime import datetime

from .errors import InvalidRepresentative, MemberNotActive, NotFound
from .models import Representative
from .store import Store


class BaseService:
    """持有存储，并提供"指定时刻必须是有效代表"等公共校验。"""

    def __init__(self, store: Store | None = None) -> None:
        self.store = store if store is not None else Store()

    def _get(self, table: dict, key: str, label: str):
        try:
            return table[key]
        except KeyError:
            raise NotFound(f"{label}不存在：{key}") from None

    def _require_valid_rep(self, representative_id: str, at: datetime) -> Representative:
        """代表在该时刻必须处于有效任期且所属会员状态正常。"""
        rep = self._get(self.store.representatives, representative_id, "代表")
        if not self.store.representative_valid_at(representative_id, at):
            member_status = self.store.member_status_at(rep.member_id, at)
            if member_status != "active":
                raise MemberNotActive(f"会员 {rep.member_id} 在该时点状态为 {member_status}，代表不能履职")
            raise InvalidRepresentative(f"代表 {representative_id} 在该时点不在有效任期内")
        return rep
