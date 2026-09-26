"""创始引导数据。

三十二家创始单位来自二十一个国家。名称均为说明性的虚构名称，
不对应现实中的任何机构（沿用 fixtures/domain.json 的样例约定）。
"""

from __future__ import annotations

from .service import GovernanceBackend

#: 工作语言：联合国六种正式语言，覆盖六大洲创始单位。
WORKING_LANGUAGES = [
    ("zh", "中文"),
    ("en", "English"),
    ("fr", "français"),
    ("es", "español"),
    ("ar", "العربية"),
    ("ru", "русский"),
]

#: (编号, 名称, 国家/地区)；共 32 家、21 个国家。
FOUNDERS: list[tuple[str, str, str]] = [
    ("M001", "华北公众科学中心", "中国"),
    ("M002", "长江科普协作会", "中国"),
    ("M003", "湾区科学教育联盟", "中国"),
    ("M004", "东京科学传播协会", "日本"),
    ("M005", "关西实验博物馆网络", "日本"),
    ("M006", "首尔市民科学馆", "韩国"),
    ("M007", "釜山青少年科学联盟", "韩国"),
    ("M008", "新加坡科学中心网络", "新加坡"),
    ("M009", "孟买科学素养基金会", "印度"),
    ("M010", "班加罗尔科普协作社", "印度"),
    ("M011", "悉尼公众科学协会", "澳大利亚"),
    ("M012", "海湾科学教育中心", "阿联酋"),
    ("M013", "开普敦科学外展网络", "南非"),
    ("M014", "开罗科学文化中心", "埃及"),
    ("M015", "伦敦科学传播学会", "英国"),
    ("M016", "曼彻斯特工业科技馆联盟", "英国"),
    ("M017", "巴黎科学与社会协会", "法国"),
    ("M018", "里昂青少年科学之家", "法国"),
    ("M019", "柏林公众科学基金会", "德国"),
    ("M020", "慕尼黑实验教育网络", "德国"),
    ("M021", "罗马科学文化促进会", "意大利"),
    ("M022", "马德里科学博物馆联盟", "西班牙"),
    ("M023", "莫斯科科学教育协会", "俄罗斯"),
    ("M024", "圣保罗科学传播网络", "巴西"),
    ("M025", "里约社区科学中心", "巴西"),
    ("M026", "墨西哥城公众科学馆", "墨西哥"),
    ("M027", "华盛顿科学素养理事会", "美国"),
    ("M028", "芝加哥科学教育联盟", "美国"),
    ("M029", "多伦多科学中心协会", "加拿大"),
    ("M030", "蒙特利尔科普网络", "加拿大"),
    ("M031", "内罗毕乡村科学推广社", "肯尼亚"),
    ("M032", "曼谷科学与社会中心", "泰国"),
]


def bootstrap(backend: GovernanceBackend, term_start: str, term_end: str,
              rules_effective_from: str) -> dict:
    """写入创始事实：32 家会员、工作语言、首版表决规则、每家一名代表。

    返回 ``{"members": [...], "reps": [...]}`` 便于演示与测试使用。
    """
    backend.seed_founders([
        {"member_id": mid, "name": name, "country": country}
        for mid, name, country in FOUNDERS
    ])
    for code, label in WORKING_LANGUAGES:
        backend.add_language(code, label)
    backend.enact_rules(
        version=1, quorum=0.5, yes_threshold=0.5,
        effective_from=rules_effective_from,
    )
    reps = []
    for mid, name, _country in FOUNDERS:
        rep_id = "R-" + mid
        backend.commission_representative(
            rep_id=rep_id, member_id=mid,
            name=f"{name}授权代表",
            term_start=term_start, term_end=term_end,
            credentials_ref=f"credentials/{mid}.pdf",
        )
        reps.append(rep_id)
    return {"members": [m for m, _n, _c in FOUNDERS], "reps": reps}
