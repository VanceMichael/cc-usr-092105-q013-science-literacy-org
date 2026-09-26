"""虚构演示数据：供示例与测试共用的组织搭建器。

所有机构、人名均为虚构，只用于说明字段关系，不对应现实中的
任何个人或组织。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from .service import GovernanceService

EPOCH = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
YEAR = timedelta(days=365)

MEMBERS = (
    ("m-east", "东方科普中心", "甲国"),
    ("m-west", "西岸科学联盟", "乙国"),
    ("m-north", "北方传播协会", "丙国"),
    ("m-south", "南方素养网络", "丁国"),
)

REPRESENTATIVES = (
    ("r-east", "m-east", "东方代表"),
    ("r-west", "m-west", "西岸代表"),
    ("r-north", "m-north", "北方代表"),
    ("r-south", "m-south", "南方代表"),
)


def build_basic_service() -> GovernanceService:
    """四家会员、两种工作语言、一套表决规则的最小组织。"""
    service = GovernanceService()
    service.add_working_language("zh", "中文", EPOCH)
    service.add_working_language("en", "English", EPOCH)
    for member_id, name, country in MEMBERS:
        service.register_member(member_id, name, country, EPOCH)
    for rep_id, member_id, name in REPRESENTATIVES:
        service.appoint_representative(rep_id, member_id, name, "primary", EPOCH, EPOCH + YEAR, EPOCH)
    service.set_voting_rules("vr-2026", 1, 2, 2, 3, EPOCH)
    return service
