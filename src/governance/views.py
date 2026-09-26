"""只读视图：成员自助视图与公众入口。

成员视图严格按机构过滤——只能看到本机构的承诺、授权附件、代表任期、
代理与表决记录；其他会员的承诺与附件不出现在响应里。

公众入口只暴露已经完成发布确认的最终生效版本：章程、项目倡议与成果。
草案、讨论用翻译稿、意见、利益冲突声明、附件等内部材料永不外泄。
"""

from __future__ import annotations

from .clock import to_text
from .state import RegistryState


def _dt(value) -> str:
    return to_text(value)


def member_dashboard(state: RegistryState, member_id: str) -> dict:
    """组装某机构会员自己可见的全部内容。"""
    member = state.members.get(member_id)
    if not member:
        raise KeyError(f"未知会员: {member_id}")

    reps = [r for r in state.reps.values() if r["member_id"] == member_id]
    rep_ids = {r["id"] for r in reps}

    profile = {
        "member_id": member["id"],
        "name": member["name"],
        "country": member["country"],
        "founder": member["founder"],
        "status": member["status"],
        "joined_at": _dt(member["joined_at"]),
        "suspensions": [
            {
                "start": _dt(s["start"]),
                "end": _dt(s["end"]) if s["end"] else None,
                "reason": s["reason"],
                "resolution_id": s.get("resolution_id"),
            }
            for s in member["suspensions"]
        ],
    }

    credentials = [
        {
            "rep_id": r["id"],
            "name": r["name"],
            "status": r["status"],
            "term_start": _dt(r["term_start"]),
            "term_end": _dt(r["term_end"]) if r["term_end"] else None,
            "credentials_ref": r["credentials_ref"],
        }
        for r in sorted(reps, key=lambda r: r["commissioned_at"])
    ]

    # 只返回本机构的承诺——附件随承诺走，绝不带出其他机构材料。
    commitments = [
        {
            "contribution_id": c["id"],
            "project_id": c["project_id"],
            "kind": c["kind"],
            "description": c["description"],
            "credit": c["credit"],
            "attachments": list(c["attachments"]),
            "status": c["status"],
            "committed_at": _dt(c["committed_at"]),
        }
        for c in state.contributions.values()
        if c["member_id"] == member_id
    ]

    coi = [
        {
            "coi_id": c["id"],
            "rep_id": c["rep_id"],
            "scope": c["scope"],
            "description": c["description"],
            "status": c["status"],
            "declared_at": _dt(c["declared_at"]),
        }
        for c in state.coi.values()
        if c["rep_id"] in rep_ids
    ]

    proxies: list[dict] = []
    ballots: list[dict] = []
    signatures: list[dict] = []
    for meeting in state.meetings.values():
        for p in meeting["proxies"]:
            if p["from_rep"] in rep_ids or p["to_rep"] in rep_ids:
                proxies.append({
                    "meeting_id": meeting["id"],
                    "from_rep": p["from_rep"],
                    "to_rep": p["to_rep"],
                    "item_id": p["item_id"],
                    "granted_at": _dt(p["granted_at"]),
                    "revoked_at": _dt(p["revoked_at"]) if p["revoked_at"] else None,
                })
    for vote in state.votes.values():
        for cast_rep, b in vote["ballots"].items():
            owner = b.get("source_rep") or cast_rep
            if owner in rep_ids:
                ballots.append({
                    "vote_id": vote["id"],
                    "meeting_id": vote["meeting_id"],
                    "item_id": vote["item_id"],
                    "choice": b["choice"],
                    "via": b["via"],
                    "cast_at": _dt(b["at"]),
                })
    for doc in state.documents.values():
        for rev, approval in doc["approvals"].items():
            if approval["by_rep"] in rep_ids or any(
                pub["by_rep"] in rep_ids and pub["rev"] == rev for pub in doc["publications"]
            ):
                signatures.append({
                    "doc_id": doc["id"],
                    "kind": doc["kind"],
                    "rev": rev,
                    "approved_at": _dt(approval["at"]),
                    "resolution_id": approval["resolution_id"],
                    "published_at": next(
                        (_dt(p["at"]) for p in doc["publications"] if p["rev"] == rev), None),
                })

    return {
        "profile": profile,
        "credentials": credentials,
        "commitments": commitments,
        "conflict_declarations": coi,
        "proxies": proxies,
        "ballots": ballots,
        "signatures": signatures,
    }


def _public_entry(state: RegistryState, doc_id: str) -> dict | None:
    doc = state.documents[doc_id]
    eff = state.effective_revision(doc_id)
    if eff is None:
        return None
    published_at = next(p["at"] for p in doc["publications"] if p["rev"] == eff["rev"])
    approval = doc["approvals"][eff["rev"]]
    return {
        "doc_id": doc["id"],
        "kind": doc["kind"],
        "project_id": doc["project_id"],
        "title": eff["title"],
        "revision": eff["rev"],
        "language": doc["original_language"],
        "body_ref": eff["body_ref"],
        "approved_by_resolution": approval["resolution_id"],
        "published_at": _dt(published_at),
    }


def public_catalog(state: RegistryState) -> dict:
    """公众入口：永远指向最终生效版本，内部材料一概不返回。"""
    entries = [e for doc_id in state.documents if (e := _public_entry(state, doc_id))]
    entries.sort(key=lambda e: (e["kind"], e["published_at"]))
    return {
        "organization": state.meta["name"] if state.meta else None,
        "charter": next((e for e in entries if e["kind"] == "charter"), None),
        "projects": [e for e in entries if e["kind"] == "initiative"],
        "deliverables": [e for e in entries if e["kind"] == "deliverable"],
    }
