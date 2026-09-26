"""登记册状态：从只追加事件重放出来的纯函数视图。

七本登记册各管一段事实：
机构会员、代表任期、工作语言、倡议草案（含章程/成果）、资源贡献、
利益冲突声明、表决规则。会议的议程、意见、代理、投票、决议按发生时间
挂到同一条时间线上。

``RegistryState.replay(until=...)`` 可以重放到任意历史时刻：暂停区间、
任期边界、法定人数基数在那一刻是什么样就呈现什么样，而已经记录的
批准与签署永不消失。
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Any, Iterable

from .clock import parse_moment
from .store import Event

DOC_KINDS = ("charter", "initiative", "deliverable")
CHOICES = ("yes", "no", "abstain")


def _dt(value: Any) -> datetime:
    return value if isinstance(value, datetime) else parse_moment(value)


class RegistryState:
    def __init__(self) -> None:
        self.meta: dict | None = None
        self.members: dict[str, dict] = {}
        self.member_order: list[str] = []
        self.reps: dict[str, dict] = {}
        self.languages: dict[str, dict] = {}
        self.rules: dict[str, list[dict]] = {}   # code -> 版本列表，按生效时间
        self.rules_order: list[str] = []
        self.documents: dict[str, dict] = {}
        self.contributions: dict[str, dict] = {}
        self.coi: dict[str, dict] = {}
        self.meetings: dict[str, dict] = {}
        self.votes: dict[str, dict] = {}
        self.resolutions: dict[str, dict] = {}
        # 全局时间线：(at 文本, 类别, 定位字典)
        self.chronology: list[tuple[str, str, dict]] = []

    # ------------------------------------------------------------------ #
    # 重放
    # ------------------------------------------------------------------ #
    @classmethod
    def replay(cls, events: Iterable[Event], until: datetime | str | None = None) -> "RegistryState":
        state = cls()
        cutoff = _dt(until) if until is not None else None
        for ev in events:
            if cutoff is not None and ev.at > cutoff:
                continue
            state.apply(ev)
        return state

    def apply(self, ev: Event) -> None:
        at = ev.at
        d = ev.data
        kind = ev.type
        self._seq = ev.seq
        hook = getattr(self, f"_on_{kind}", None)
        if hook is None:
            raise ValueError(f"未知事件类型: {kind}")
        hook(at, d)
        self.chronology.append((at.isoformat(), kind, d))

    # ------------------------------------------------------------------ #
    # 机构会员
    # ------------------------------------------------------------------ #
    def _on_org_seeded(self, at: datetime, d: dict) -> None:
        self.meta = {"at": at, **d}

    def _on_member_registered(self, at: datetime, d: dict) -> None:
        mid = d["member_id"]
        self.members[mid] = {
            "id": mid,
            "name": d["name"],
            "country": d["country"],
            "founder": d.get("founder", False),
            "joined_at": at,
            "status": "active",
            "status_since": at,
            "suspensions": [],
        }
        self.member_order.append(mid)

    def _on_member_suspended(self, at: datetime, d: dict) -> None:
        m = self.members[d["member_id"]]
        interval = {"start": at, "end": None, "reason": d.get("reason", "")}
        m["suspensions"].append(interval)
        m["status"] = "suspended"
        m["status_since"] = at
        m["_open_suspension"] = interval

    def _on_member_reinstated(self, at: datetime, d: dict) -> None:
        m = self.members[d["member_id"]]
        open_interval = m.get("_open_suspension")
        if open_interval is not None:
            open_interval["end"] = at
            open_interval["resolution_id"] = d.get("resolution_id")
        m.pop("_open_suspension", None)
        m["status"] = "active"
        m["status_since"] = at

    # ------------------------------------------------------------------ #
    # 代表任期
    # ------------------------------------------------------------------ #
    def _on_representative_commissioned(self, at: datetime, d: dict) -> None:
        self.reps[d["rep_id"]] = {
            "id": d["rep_id"],
            "member_id": d["member_id"],
            "name": d["name"],
            "term_start": parse_moment(d["term_start"]),
            "term_end": parse_moment(d["term_end"]) if d.get("term_end") else None,
            "credentials_ref": d.get("credentials_ref"),
            "status": "active",
            "commissioned_at": at,
        }

    def _on_representative_revoked(self, at: datetime, d: dict) -> None:
        rep = self.reps[d["rep_id"]]
        rep["status"] = "revoked"
        rep["revoked_at"] = at
        rep["revoke_reason"] = d.get("reason", "")

    # ------------------------------------------------------------------ #
    # 工作语言
    # ------------------------------------------------------------------ #
    def _on_language_added(self, at: datetime, d: dict) -> None:
        self.languages[d["code"]] = {"code": d["code"], "name": d["name"], "added_at": at, "status": "working"}

    def _on_language_archived(self, at: datetime, d: dict) -> None:
        self.languages[d["code"]]["status"] = "archived"

    # ------------------------------------------------------------------ #
    # 表决规则（保留全部历史版本）
    # ------------------------------------------------------------------ #
    def _on_rules_enacted(self, at: datetime, d: dict) -> None:
        code = d["code"]
        version = {
            "code": code,
            "version": d["version"],
            "quorum": d["quorum"],
            "thresholds": d["thresholds"],
            "weight_mode": d.get("weight_mode", "one_member_one_vote"),
            "effective_from": parse_moment(d["effective_from"]),
            "supersedes": d.get("supersedes"),
            "enacted_at": at,
            "resolution_id": d.get("resolution_id"),
        }
        self.rules.setdefault(code, []).append(version)
        if code not in self.rules_order:
            self.rules_order.append(code)
        self.rules[code].sort(key=lambda v: v["effective_from"])

    # ------------------------------------------------------------------ #
    # 倡议/章程/成果草案与修订
    # ------------------------------------------------------------------ #
    def _on_document_registered(self, at: datetime, d: dict) -> None:
        self.documents[d["doc_id"]] = {
            "id": d["doc_id"],
            "kind": d["kind"],
            "project_id": d.get("project_id"),
            "title": d["title"],
            "original_language": d["original_language"],
            "registered_at": at,
            "revisions": [],
            "translations": defaultdict(list),
            "approvals": {},       # rev -> 批准记录
            "publications": [],    # 按时间排列的发布确认
        }

    def _on_revision_proposed(self, at: datetime, d: dict) -> None:
        doc = self.documents[d["doc_id"]]
        doc["revisions"].append({
            "rev": d["rev"],
            "base_rev": d.get("base_rev"),
            "language": d["language"],
            "title": d["title"],
            "summary": d.get("summary", ""),
            "body_ref": d["body_ref"],
            "editors": list(d.get("editors", [])),
            "item_id": d.get("item_id"),
            "seq": self._seq,
            "at": at,
        })

    def _on_translation_submitted(self, at: datetime, d: dict) -> None:
        doc = self.documents[d["doc_id"]]
        doc["translations"][d["rev"]].append({
            "language": d["language"],
            "body_ref": d["body_ref"],
            "translator_rep": d["translator_rep"],
            "purpose": "discussion",   # 翻译稿只服务讨论
            "at": at,
        })

    def _on_original_approved(self, at: datetime, d: dict) -> None:
        doc = self.documents[d["doc_id"]]
        doc["approvals"][d["rev"]] = {
            "rev": d["rev"],
            "language": d["language"],
            "resolution_id": d["resolution_id"],
            "by_rep": d["by_rep"],
            "at": at,
        }

    def _on_publish_confirmed(self, at: datetime, d: dict) -> None:
        doc = self.documents[d["doc_id"]]
        doc["publications"].append({"rev": d["rev"], "by_rep": d["by_rep"], "at": at})

    # ------------------------------------------------------------------ #
    # 资源贡献
    # ------------------------------------------------------------------ #
    def _on_contribution_committed(self, at: datetime, d: dict) -> None:
        self.contributions[d["contribution_id"]] = {
            "id": d["contribution_id"],
            "member_id": d["member_id"],
            "project_id": d.get("project_id"),
            "kind": d["kind"],
            "description": d["description"],
            "credit": d.get("credit", ""),
            "attachments": list(d.get("attachments", [])),
            "committed_at": at,
            "status": "committed",
        }

    def _on_contribution_withdrawn(self, at: datetime, d: dict) -> None:
        c = self.contributions[d["contribution_id"]]
        c["status"] = "withdrawn"
        c["withdrawn_at"] = at
        c["withdraw_reason"] = d.get("reason", "")

    # ------------------------------------------------------------------ #
    # 利益冲突声明
    # ------------------------------------------------------------------ #
    def _on_coi_declared(self, at: datetime, d: dict) -> None:
        self.coi[d["coi_id"]] = {
            "id": d["coi_id"],
            "rep_id": d["rep_id"],
            "scope": d["scope"],
            "description": d.get("description", ""),
            "declared_at": at,
            "status": "open",
        }

    def _on_coi_resolved(self, at: datetime, d: dict) -> None:
        c = self.coi[d["coi_id"]]
        c["status"] = "resolved"
        c["resolved_at"] = at

    # ------------------------------------------------------------------ #
    # 会议：议程、意见、代理、出席、投票、决议
    # ------------------------------------------------------------------ #
    def _on_meeting_scheduled(self, at: datetime, d: dict) -> None:
        self.meetings[d["meeting_id"]] = {
            "id": d["meeting_id"],
            "title": d["title"],
            "zone": d.get("zone", "UTC"),
            "scheduled_for": parse_moment(d["starts_at"]),
            "scheduled_at": at,
            "status": "scheduled",
            "opened_at": None,
            "closed_at": None,
            "agenda": [],
            "comments": [],
            "proxies": [],
            "attendance": {},
            "item_votes": defaultdict(list),
        }

    def _on_meeting_opened(self, at: datetime, d: dict) -> None:
        m = self.meetings[d["meeting_id"]]
        m["status"] = "open"
        m["opened_at"] = at

    def _on_meeting_closed(self, at: datetime, d: dict) -> None:
        m = self.meetings[d["meeting_id"]]
        m["status"] = "closed"
        m["closed_at"] = at

    def _on_agenda_added(self, at: datetime, d: dict) -> None:
        m = self.meetings[d["meeting_id"]]
        m["agenda"].append({
            "item_id": d["item_id"],
            "seq": d["seq"],
            "title": d["title"],
            "subject": d.get("subject"),
            "matter_type": d["matter_type"],
            "added_at": at,
        })

    def _on_comment_posted(self, at: datetime, d: dict) -> None:
        m = self.meetings[d["meeting_id"]]
        m["comments"].append({
            "comment_id": d["comment_id"],
            "item_id": d["item_id"],
            "rep_id": d["rep_id"],
            "text": d["text"],
            "seq": self._seq,
            "at": at,
        })

    def _on_proxy_granted(self, at: datetime, d: dict) -> None:
        m = self.meetings[d["meeting_id"]]
        m["proxies"].append({
            "from_rep": d["from_rep"],
            "to_rep": d["to_rep"],
            "item_id": d.get("item_id"),
            "granted_at": at,
            "revoked_at": None,
        })

    def _on_proxy_revoked(self, at: datetime, d: dict) -> None:
        m = self.meetings[d["meeting_id"]]
        for p in reversed(m["proxies"]):
            if (
                p["from_rep"] == d["from_rep"]
                and p["to_rep"] == d["to_rep"]
                and p["item_id"] == d.get("item_id")
                and p["revoked_at"] is None
            ):
                p["revoked_at"] = at
                break

    def _on_attendance_marked(self, at: datetime, d: dict) -> None:
        m = self.meetings[d["meeting_id"]]
        m["attendance"][d["rep_id"]] = {"at": at, "method": d.get("method", "present")}

    def _on_vote_opened(self, at: datetime, d: dict) -> None:
        m = self.meetings[d["meeting_id"]]
        vote = {
            "id": d["vote_id"],
            "meeting_id": d["meeting_id"],
            "item_id": d["item_id"],
            "subject": d["subject"],
            "matter_type": d["matter_type"],
            "opened_at": at,
            "opened_seq": self._seq,
            "closed_at": None,
            "status": "open",
            "rules_snapshot": d["rules_snapshot"],
            "ballots": {},
            "result": None,
        }
        self.votes[d["vote_id"]] = vote
        m["item_votes"][d["item_id"]].append(d["vote_id"])

    def _on_ballot_cast(self, at: datetime, d: dict) -> None:
        vote = self.votes[d["vote_id"]]
        vote["ballots"][d["voter_rep"]] = {
            "choice": d["choice"],
            "weight": d["weight"],
            "at": at,
            "via": d.get("via", "direct"),
            "source_rep": d.get("source_rep"),
        }

    def _on_vote_closed(self, at: datetime, d: dict) -> None:
        vote = self.votes[d["vote_id"]]
        vote["status"] = "closed"
        vote["closed_at"] = at
        vote["closed_seq"] = self._seq
        vote["result"] = d["result"]

    def _on_resolution_recorded(self, at: datetime, d: dict) -> None:
        m = self.meetings[d["meeting_id"]]
        resolution = {
            "id": d["resolution_id"],
            "meeting_id": d["meeting_id"],
            "item_id": d["item_id"],
            "vote_id": d["vote_id"],
            "text": d["text"],
            "effects": d.get("effects", {}),
            "seq": self._seq,
            "at": at,
        }
        self.resolutions[d["resolution_id"]] = resolution
        m.setdefault("resolutions", []).append(resolution)

    # ------------------------------------------------------------------ #
    # 查询
    # ------------------------------------------------------------------ #
    def member_active(self, member_id: str, at: datetime) -> bool:
        m = self.members.get(member_id)
        if not m:
            return False
        for interval in m["suspensions"]:
            if interval["start"] <= at and (interval["end"] is None or at < interval["end"]):
                return False
        return True

    def valid_rep(self, rep_id: str | None, at: datetime) -> dict | None:
        """返回有效代表记录；任期外、授权撤销、所属会员暂停均无效。"""
        if not rep_id:
            return None
        rep = self.reps.get(rep_id)
        if not rep or rep["status"] != "active":
            return None
        if not (rep["term_start"] <= at and (rep["term_end"] is None or at < rep["term_end"])):
            return None
        if not self.member_active(rep["member_id"], at):
            return None
        return rep

    def working_language(self, code: str, at: datetime) -> bool:
        lang = self.languages.get(code)
        return bool(lang and lang["status"] == "working" and lang["added_at"] <= at)

    def open_coi(self, rep_id: str, scope: dict | None, at: datetime) -> dict | None:
        """查代表对某议题是否有未解除的利益冲突。scope=None 表示全局自避。"""
        for c in self.coi.values():
            if c["rep_id"] != rep_id or c["status"] != "open":
                continue
            if not (c["declared_at"] <= at):
                continue
            if scope is None or c["scope"] is None:
                if scope is None and c["scope"] is None:
                    return c
                continue
            if c["scope"].get("kind") == scope.get("kind") and (
                c["scope"].get("id") in (None, scope.get("id"))
            ):
                return c
        return None

    def rules_in_force(self, code: str, at: datetime) -> dict | None:
        versions = self.rules.get(code, [])
        current = None
        for v in versions:
            if v["effective_from"] <= at:
                current = v
            else:
                break
        return current

    def head_revision(self, doc_id: str) -> dict | None:
        revs = self.documents[doc_id]["revisions"]
        return revs[-1] if revs else None

    def revision(self, doc_id: str, rev: int) -> dict | None:
        for r in self.documents[doc_id]["revisions"]:
            if r["rev"] == rev:
                return r
        return None

    def effective_revision(self, doc_id: str, at: datetime | None = None) -> dict | None:
        """最新一个已发布确认的修订；早于 ``at`` 的才算（用于历史时点视图）。"""
        doc = self.documents.get(doc_id)
        if not doc or not doc["publications"]:
            return None
        current = None
        for pub in doc["publications"]:
            if at is not None and pub["at"] > at:
                continue
            current = self.revision(doc_id, pub["rev"])
        return current

    def item_thread(self, meeting_id: str, item_id: str) -> list[dict]:
        """把议程项相关的修订、意见、投票、决议按发生时间串成一条线。"""
        m = self.meetings[meeting_id]
        thread: list[dict] = []
        for c in m["comments"]:
            if c["item_id"] == item_id:
                thread.append({"at": c["at"], "seq": c["seq"], "type": "comment", "data": c})
        for vote_id in m["item_votes"].get(item_id, []):
            v = self.votes[vote_id]
            thread.append({"at": v["opened_at"], "seq": v["opened_seq"],
                           "type": "vote_opened", "data": {"vote_id": v["id"]}})
            if v["closed_at"]:
                thread.append({"at": v["closed_at"], "seq": v["closed_seq"],
                               "type": "vote_closed", "data": v["result"]})
        for r in m.get("resolutions", []):
            if r["item_id"] == item_id:
                thread.append({"at": r["at"], "seq": r["seq"],
                               "type": "resolution", "data": r})
        for doc in self.documents.values():
            for rev in doc["revisions"]:
                if rev.get("item_id") == item_id:
                    thread.append({"at": rev["at"], "seq": rev["seq"],
                                   "type": "revision", "data": {
                        "doc_id": doc["id"], "kind": doc["kind"], **rev,
                    }})
        thread.sort(key=lambda x: (x["at"], x["seq"]))
        return thread
