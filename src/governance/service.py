"""治理服务：登记册维护与议事流程的全部业务规则。

每条命令先重放事件得到当前状态，校验通过后再只追加一条事件。
关键约束：

* 原文批准只认工作语言原文修订；翻译稿用途固定为讨论，永远不能被批准。
* 原文批准与发布确认都必须由当时在有效任期内、所属会员未被暂停的代表完成；
  事后撤销授权或暂停会员不会抹掉已完成的批准、签署与发布。
* 投票开启时冻结法定人数基数与规则版本；会议进行中暂停/恢复会员、
  修改规则都不影响已开场次的计票。
* 联合编辑采用乐观并发：修订必须基于当前首版，冲突方需要 rebase 后重提。
* 代理只能覆盖未撤销、授权代表仍有效、且无未解除利益冲突的会员。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Callable, Sequence

from .clock import now, parse_moment
from .state import DOC_KINDS, CHOICES, RegistryState
from .store import Event, EventStore

MATTER_TYPES = ("procedural", "substantive")


class GovernanceError(Exception):
    """业务规则被违反；调用方应修正命令后重试。"""


class GovernanceBackend:
    def __init__(self, store: EventStore, clock: Callable[[], datetime] | None = None,
                 rules_code: str = "assembly"):
        self.store = store
        self.clock = clock or now
        self.rules_code = rules_code

    # ------------------------------------------------------------------ #
    # 内部工具
    # ------------------------------------------------------------------ #
    def _state(self, until: datetime | str | None = None) -> RegistryState:
        return RegistryState.replay(self.store.replay(), until=until)

    def _emit(self, event_type: str, data: dict, cmd: str | None = None) -> Event:
        return self.store.append(event_type, data, at=self.clock(), cmd=cmd)

    def _dedup(self, cmd: str | None) -> Event | None:
        """带幂等键的命令重放时直接返回已落库事件，不再走校验。"""
        if not cmd:
            return None
        if cmd not in self.store.seen_cmds():
            return None
        return next(ev for ev in self.store.replay() if ev.cmd == cmd)

    def _at(self) -> datetime:
        return self.clock()

    def _require_rep(self, state: RegistryState, rep_id: str, what: str) -> dict:
        rep = state.valid_rep(rep_id, self._at())
        if rep is None:
            raise GovernanceError(f"{what}必须由有效代表完成（{rep_id} 任期外、授权已撤销或会员已暂停）")
        return rep

    def _require_meeting_open(self, state: RegistryState, meeting_id: str) -> dict:
        m = state.meetings.get(meeting_id)
        if not m:
            raise GovernanceError(f"未知会议: {meeting_id}")
        if m["status"] != "open":
            raise GovernanceError(f"会议 {meeting_id} 当前未开场（状态 {m['status']}）")
        return m

    # ------------------------------------------------------------------ #
    # 创始引导
    # ------------------------------------------------------------------ #
    def seed_founders(self, records: Sequence[dict]) -> list[Event]:
        """一次性写入组织事实与三十二家创始单位。"""
        state = self._state()
        if state.meta is not None:
            raise GovernanceError("创始登记只能执行一次")
        if len(records) != 32:
            raise GovernanceError(f"创始单位必须为三十二家，收到 {len(records)} 家")
        events = [self._emit("org_seeded", {
            "name": "世界公众科学素质组织",
            "founder_count": 32,
            "note": "依托长期大会和国际合作伙伴网络成立",
        }, cmd="seed:org")]
        for i, r in enumerate(records, 1):
            mid = r["member_id"]
            if mid in state.members:
                raise GovernanceError(f"会员编号重复: {mid}")
            events.append(self._emit("member_registered", {
                "member_id": mid,
                "name": r["name"],
                "country": r["country"],
                "founder": True,
            }, cmd=f"seed:founder:{mid}"))
        return events

    # ------------------------------------------------------------------ #
    # 机构会员登记册
    # ------------------------------------------------------------------ #
    def register_member(self, member_id: str, name: str, country: str, *,
                        founder: bool = False) -> Event:
        state = self._state()
        if member_id in state.members:
            raise GovernanceError(f"会员已存在: {member_id}")
        return self._emit("member_registered", {
            "member_id": member_id, "name": name, "country": country, "founder": founder,
        })

    def suspend_member(self, member_id: str, reason: str, by_rep: str) -> Event:
        state = self._state()
        self._require_rep(state, by_rep, "暂停会员")
        if member_id not in state.members:
            raise GovernanceError(f"未知会员: {member_id}")
        if not state.member_active(member_id, self._at()):
            raise GovernanceError(f"会员 {member_id} 已处于暂停状态")
        return self._emit("member_suspended", {
            "member_id": member_id, "reason": reason, "by_rep": by_rep,
        })

    def reinstate_member(self, member_id: str, resolution_id: str, by_rep: str) -> Event:
        """恢复会籍必须依据已通过的会议决议。"""
        state = self._state()
        self._require_rep(state, by_rep, "恢复会籍")
        if state.member_active(member_id, self._at()):
            raise GovernanceError(f"会员 {member_id} 未处于暂停状态")
        resolution = state.resolutions.get(resolution_id)
        if not resolution or state.votes[resolution["vote_id"]]["result"]["status"] != "passed":
            raise GovernanceError("恢复会籍必须引用已通过的决议")
        if resolution["effects"].get("reinstate_member") != member_id:
            raise GovernanceError("决议效力不包含恢复该会员")
        return self._emit("member_reinstated", {
            "member_id": member_id, "resolution_id": resolution_id, "by_rep": by_rep,
        })

    # ------------------------------------------------------------------ #
    # 代表任期登记册
    # ------------------------------------------------------------------ #
    def commission_representative(self, rep_id: str, member_id: str, name: str,
                                  term_start: str, term_end: str | None = None,
                                  credentials_ref: str | None = None) -> Event:
        state = self._state()
        if rep_id in state.reps:
            raise GovernanceError(f"代表编号已存在: {rep_id}")
        if member_id not in state.members:
            raise GovernanceError(f"未知会员: {member_id}")
        start = parse_moment(term_start)
        end = parse_moment(term_end) if term_end else None
        if end and end <= start:
            raise GovernanceError("任期结束必须晚于开始")
        return self._emit("representative_commissioned", {
            "rep_id": rep_id, "member_id": member_id, "name": name,
            "term_start": term_start, "term_end": term_end,
            "credentials_ref": credentials_ref,
        })

    def revoke_representative(self, rep_id: str, reason: str, by_rep: str) -> Event:
        state = self._state()
        self._require_rep(state, by_rep, "撤销代表授权")
        rep = state.reps.get(rep_id)
        if not rep or rep["status"] != "active":
            raise GovernanceError(f"代表 {rep_id} 不处于有效状态")
        return self._emit("representative_revoked", {
            "rep_id": rep_id, "reason": reason, "by_rep": by_rep,
        })

    # ------------------------------------------------------------------ #
    # 工作语言登记册
    # ------------------------------------------------------------------ #
    def add_language(self, code: str, name: str) -> Event:
        state = self._state()
        if code in state.languages:
            raise GovernanceError(f"语言已登记: {code}")
        return self._emit("language_added", {"code": code, "name": name})

    def archive_language(self, code: str) -> Event:
        state = self._state()
        if not state.working_language(code, self._at()):
            raise GovernanceError(f"{code} 不是现行工作语言")
        return self._emit("language_archived", {"code": code})

    # ------------------------------------------------------------------ #
    # 表决规则登记册（多版本，按生效时间切换）
    # ------------------------------------------------------------------ #
    def enact_rules(self, version: int, quorum: float, yes_threshold: float,
                    effective_from: str, *, supersedes: int | None = None,
                    resolution_id: str | None = None) -> Event:
        state = self._state()
        if not (0.0 < quorum <= 1.0 and 0.0 < yes_threshold <= 1.0):
            raise GovernanceError("法定人数比例与通过阈值必须在 (0, 1] 区间")
        versions = state.rules.get(self.rules_code, [])
        if any(v["version"] == version for v in versions):
            raise GovernanceError(f"规则版本 {version} 已存在")
        if parse_moment(effective_from) <= self._at() and versions:
            raise GovernanceError("规则生效时间不能早于制定时间，需面向未来生效")
        return self._emit("rules_enacted", {
            "code": self.rules_code,
            "version": version,
            "quorum": quorum,
            "thresholds": {"yes_fraction": yes_threshold},
            "weight_mode": "one_member_one_vote",
            "effective_from": effective_from,
            "supersedes": supersedes,
            "resolution_id": resolution_id,
        })

    # ------------------------------------------------------------------ #
    # 倡议/章程/成果草案、修订与翻译
    # ------------------------------------------------------------------ #
    def register_document(self, doc_id: str, kind: str, title: str,
                          original_language: str, *, project_id: str | None = None) -> Event:
        state = self._state()
        if kind not in DOC_KINDS:
            raise GovernanceError(f"文件类型必须是 {DOC_KINDS} 之一")
        if doc_id in state.documents:
            raise GovernanceError(f"文件已登记: {doc_id}")
        if not state.working_language(original_language, self._at()):
            raise GovernanceError(f"原文语言 {original_language} 不是现行工作语言")
        if kind == "deliverable" and not project_id:
            raise GovernanceError("成果必须归属一个项目")
        return self._emit("document_registered", {
            "doc_id": doc_id, "kind": kind, "project_id": project_id,
            "title": title, "original_language": original_language,
        })

    def propose_revision(self, doc_id: str, base_rev: int | None, language: str,
                         title: str, body_ref: str, editors: Sequence[str],
                         *, item_id: str | None = None, summary: str = "",
                         cmd: str | None = None) -> Event:
        """联合编辑入口：base_rev 必须等于当前首版，否则要求 rebase。"""
        if (dup := self._dedup(cmd)) is not None:
            return dup
        state = self._state()
        doc = state.documents.get(doc_id)
        if not doc:
            raise GovernanceError(f"未知文件: {doc_id}")
        head = state.head_revision(doc_id)
        expected_base = head["rev"] if head else None
        if base_rev != expected_base:
            raise GovernanceError(
                f"联合编辑冲突：修订基于 r{base_rev}，当前首版为 r{expected_base}，请 rebase 后重提")
        if language != doc["original_language"]:
            raise GovernanceError("修订只能针对原文语言；译文请走翻译稿通道且仅用于讨论")
        for rep_id in editors:
            self._require_rep(state, rep_id, f"修订 {doc_id} 的联合编辑")
        new_rev = (expected_base or 0) + 1
        return self._emit("revision_proposed", {
            "doc_id": doc_id, "rev": new_rev, "base_rev": base_rev,
            "language": language, "title": title, "summary": summary,
            "body_ref": body_ref, "editors": list(editors), "item_id": item_id,
        }, cmd=cmd)

    def submit_translation(self, doc_id: str, rev: int, language: str,
                           body_ref: str, translator_rep: str) -> Event:
        state = self._state()
        self._require_rep(state, translator_rep, "提交翻译稿")
        doc = state.documents.get(doc_id)
        if not doc or not state.revision(doc_id, rev):
            raise GovernanceError(f"文件 {doc_id} 不存在修订 r{rev}")
        if language == doc["original_language"]:
            raise GovernanceError("翻译稿语言不能与原文相同")
        if not state.working_language(language, self._at()):
            raise GovernanceError(f"译文语言 {language} 不是现行工作语言")
        return self._emit("translation_submitted", {
            "doc_id": doc_id, "rev": rev, "language": language,
            "body_ref": body_ref, "translator_rep": translator_rep,
        })

    # ------------------------------------------------------------------ #
    # 资源贡献登记册
    # ------------------------------------------------------------------ #
    def commit_contribution(self, contribution_id: str, member_id: str, kind: str,
                            description: str, *, by_rep: str, credit: str = "",
                            attachments: Sequence[str] | None = None,
                            project_id: str | None = None, cmd: str | None = None) -> Event:
        if (dup := self._dedup(cmd)) is not None:
            return dup
        state = self._state()
        rep = self._require_rep(state, by_rep, "登记资源贡献")
        if rep["member_id"] != member_id:
            raise GovernanceError("代表只能为本机构登记承诺")
        if contribution_id in state.contributions:
            raise GovernanceError(f"贡献编号已存在: {contribution_id}")
        return self._emit("contribution_committed", {
            "contribution_id": contribution_id, "member_id": member_id,
            "project_id": project_id, "kind": kind, "description": description,
            "credit": credit, "by_rep": by_rep, "attachments": list(attachments or []),
        }, cmd=cmd)

    def withdraw_contribution(self, contribution_id: str, by_rep: str,
                              reason: str = "") -> Event:
        """撤回承诺保留历史记录；署名与时间不被删除。"""
        state = self._state()
        rep = self._require_rep(state, by_rep, "撤回资源贡献")
        c = state.contributions.get(contribution_id)
        if not c:
            raise GovernanceError(f"未知贡献: {contribution_id}")
        if rep["member_id"] != c["member_id"]:
            raise GovernanceError("只能撤回本机构的承诺")
        if c["status"] != "committed":
            raise GovernanceError("承诺已被撤回")
        return self._emit("contribution_withdrawn", {
            "contribution_id": contribution_id, "by_rep": by_rep, "reason": reason,
        })

    # ------------------------------------------------------------------ #
    # 利益冲突声明登记册
    # ------------------------------------------------------------------ #
    def declare_coi(self, coi_id: str, rep_id: str, scope: dict | None,
                    description: str = "") -> Event:
        state = self._state()
        self._require_rep(state, rep_id, "提交利益冲突声明")
        if coi_id in state.coi:
            raise GovernanceError(f"利益冲突声明编号已存在: {coi_id}")
        return self._emit("coi_declared", {
            "coi_id": coi_id, "rep_id": rep_id, "scope": scope, "description": description,
        })

    def resolve_coi(self, coi_id: str, by_rep: str) -> Event:
        state = self._state()
        self._require_rep(state, by_rep, "解除利益冲突")
        coi = state.coi.get(coi_id)
        if not coi:
            raise GovernanceError(f"未知利益冲突声明: {coi_id}")
        if coi["status"] != "open":
            raise GovernanceError("该利益冲突已解除")
        return self._emit("coi_resolved", {"coi_id": coi_id, "by_rep": by_rep})

    # ------------------------------------------------------------------ #
    # 会议时间线
    # ------------------------------------------------------------------ #
    def schedule_meeting(self, meeting_id: str, title: str, starts_at: str,
                         zone: str = "UTC") -> Event:
        state = self._state()
        if meeting_id in state.meetings:
            raise GovernanceError(f"会议已安排: {meeting_id}")
        parse_moment(starts_at)  # 仅做格式校验
        return self._emit("meeting_scheduled", {
            "meeting_id": meeting_id, "title": title,
            "starts_at": starts_at, "zone": zone,
        })

    def open_meeting(self, meeting_id: str) -> Event:
        state = self._state()
        m = state.meetings.get(meeting_id)
        if not m:
            raise GovernanceError(f"未知会议: {meeting_id}")
        if m["status"] != "scheduled":
            raise GovernanceError("会议只能开场一次")
        return self._emit("meeting_opened", {"meeting_id": meeting_id})

    def close_meeting(self, meeting_id: str) -> Event:
        state = self._state()
        m = state.meetings.get(meeting_id)
        if not m or m["status"] != "open":
            raise GovernanceError("只有进行中的会议可以结束")
        return self._emit("meeting_closed", {"meeting_id": meeting_id})

    def add_agenda_item(self, meeting_id: str, item_id: str, seq: int, title: str,
                        matter_type: str, *, subject: dict | None = None) -> Event:
        state = self._state()
        if meeting_id not in state.meetings:
            raise GovernanceError(f"未知会议: {meeting_id}")
        if matter_type not in MATTER_TYPES:
            raise GovernanceError(f"事项类型必须是 {MATTER_TYPES} 之一")
        if any(i["item_id"] == item_id for i in state.meetings[meeting_id]["agenda"]):
            raise GovernanceError(f"议程项编号 {item_id} 已存在")
        if any(i["seq"] == seq for i in state.meetings[meeting_id]["agenda"]):
            raise GovernanceError(f"议程序号 {seq} 已占用")
        return self._emit("agenda_added", {
            "meeting_id": meeting_id, "item_id": item_id, "seq": seq, "title": title,
            "matter_type": matter_type, "subject": subject,
        })

    def post_comment(self, meeting_id: str, item_id: str, rep_id: str, text: str) -> Event:
        state = self._state()
        self._require_meeting_open(state, meeting_id)
        self._require_rep(state, rep_id, "发表意见")
        return self._emit("comment_posted", {
            "meeting_id": meeting_id, "item_id": item_id,
            "comment_id": f"{meeting_id}-C-{uuid.uuid4().hex[:10]}",
            "rep_id": rep_id, "text": text,
        })

    def grant_proxy(self, meeting_id: str, from_rep: str, to_rep: str,
                    item_id: str | None = None) -> Event:
        state = self._state()
        m = self._require_meeting_open(state, meeting_id)
        source = self._require_rep(state, from_rep, "授予代理")
        holder = self._require_rep(state, to_rep, "接受代理")
        if source["member_id"] == holder["member_id"]:
            raise GovernanceError("代理只能授予其他机构的代表")
        for p in m["proxies"]:
            if (p["from_rep"] == from_rep and p["to_rep"] == to_rep
                    and p["item_id"] == item_id and p["revoked_at"] is None):
                raise GovernanceError("该项代理授权已存在")
        return self._emit("proxy_granted", {
            "meeting_id": meeting_id, "from_rep": from_rep,
            "to_rep": to_rep, "item_id": item_id,
        })

    def revoke_proxy(self, meeting_id: str, from_rep: str, to_rep: str,
                     item_id: str | None = None) -> Event:
        state = self._state()
        self._require_meeting_open(state, meeting_id)
        m = state.meetings[meeting_id]
        alive = [p for p in m["proxies"] if p["revoked_at"] is None
                 and p["from_rep"] == from_rep and p["to_rep"] == to_rep
                 and p["item_id"] == item_id]
        if not alive:
            raise GovernanceError("没有对应的有效代理授权")
        return self._emit("proxy_revoked", {
            "meeting_id": meeting_id, "from_rep": from_rep,
            "to_rep": to_rep, "item_id": item_id,
        })

    def mark_attendance(self, meeting_id: str, rep_id: str, method: str = "present") -> Event:
        state = self._state()
        self._require_meeting_open(state, meeting_id)
        self._require_rep(state, rep_id, "登记出席")
        return self._emit("attendance_marked", {
            "meeting_id": meeting_id, "rep_id": rep_id, "method": method,
        })

    # ------------------------------------------------------------------ #
    # 表决
    # ------------------------------------------------------------------ #
    def _agenda_item(self, state: RegistryState, meeting_id: str, item_id: str) -> dict:
        for item in state.meetings[meeting_id]["agenda"]:
            if item["item_id"] == item_id:
                return item
        raise GovernanceError(f"议程中没有事项 {item_id}")

    def open_vote(self, meeting_id: str, item_id: str, vote_id: str,
                  subject: str, matter_type: str) -> Event:
        state = self._state()
        self._require_meeting_open(state, meeting_id)
        self._agenda_item(state, meeting_id, item_id)
        if vote_id in state.votes:
            raise GovernanceError(f"投票编号已存在: {vote_id}")
        if matter_type not in MATTER_TYPES:
            raise GovernanceError(f"事项类型必须是 {MATTER_TYPES} 之一")
        rules = state.rules_in_force(self.rules_code, self._at())
        if rules is None:
            raise GovernanceError("尚无生效的表决规则，无法开启投票")
        active_members = sorted(
            mid for mid in state.member_order if state.member_active(mid, self._at()))
        snapshot = {
            "rules_code": rules["code"],
            "rules_version": rules["version"],
            "quorum": rules["quorum"],
            "yes_threshold": rules["thresholds"]["yes_fraction"],
            "base_members": active_members,  # 法定人数基数在此冻结
        }
        return self._emit("vote_opened", {
            "vote_id": vote_id, "meeting_id": meeting_id, "item_id": item_id,
            "subject": subject, "matter_type": matter_type,
            "rules_snapshot": snapshot,
        })

    def _active_proxy(self, state: RegistryState, meeting_id: str,
                      source_rep: str, holder_rep: str, item_id: str) -> dict | None:
        for p in state.meetings[meeting_id]["proxies"]:
            if p["revoked_at"] is not None:
                continue
            if p["from_rep"] != source_rep or p["to_rep"] != holder_rep:
                continue
            if p["item_id"] in (None, item_id):
                return p
        return None

    def cast_ballot(self, vote_id: str, voter_rep: str, choice: str,
                    *, on_behalf_of: str | None = None, cmd: str | None = None) -> Event:
        if (dup := self._dedup(cmd)) is not None:
            return dup
        state = self._state()
        vote = state.votes.get(vote_id)
        if not vote or vote["status"] != "open":
            raise GovernanceError("投票不存在或已结束")
        if choice not in CHOICES:
            raise GovernanceError(f"票决意见必须是 {CHOICES} 之一")
        voter = self._require_rep(state, voter_rep, "投票")
        meeting = state.meetings[vote["meeting_id"]]
        if voter_rep not in meeting["attendance"]:
            raise GovernanceError("受托人未登记出席，不能现场投票（可远程登记出席）")
        item = self._agenda_item(state, vote["meeting_id"], vote["item_id"])
        scope = (item.get("subject") or {}).get("coi_scope")

        if on_behalf_of is None:
            voting_member = voter["member_id"]
            source_rep = None
            via = "direct"
            if state.open_coi(voter_rep, scope, self._at()):
                raise GovernanceError("存在未解除的利益冲突，该事项必须回避，不能投票")
        else:
            source = self._require_rep(state, on_behalf_of, "代理投票的授权方")
            if self._active_proxy(state, vote["meeting_id"], on_behalf_of, voter_rep,
                                  vote["item_id"]) is None:
                raise GovernanceError("没有覆盖本事项的有效代理授权")
            if state.open_coi(on_behalf_of, scope, self._at()):
                raise GovernanceError("授权方对本事项有未解除利益冲突，不能通过代理投票")
            voting_member = source["member_id"]
            source_rep = on_behalf_of
            via = "proxy"

        if voting_member not in vote["rules_snapshot"]["base_members"]:
            raise GovernanceError("投票开启后该会员不在冻结的法定人数基数内，不能参加本场表决")
        for cast_rep, ballot in vote["ballots"].items():
            owner = ballot.get("source_rep") or cast_rep
            if state.reps[owner]["member_id"] == voting_member:
                raise GovernanceError("该会员在本场投票中已经表决，不能重复投票")
        return self._emit("ballot_cast", {
            "vote_id": vote_id, "voter_rep": voter_rep, "choice": choice,
            "weight": 1, "via": via, "source_rep": source_rep,
        }, cmd=cmd)

    def close_vote(self, vote_id: str) -> Event:
        state = self._state()
        vote = state.votes.get(vote_id)
        if not vote or vote["status"] != "open":
            raise GovernanceError("投票不存在或已结束")
        snap = vote["rules_snapshot"]
        members_voted = set()
        tally = {c: 0 for c in CHOICES}
        for cast_rep, b in vote["ballots"].items():
            owner = b.get("source_rep") or cast_rep
            members_voted.add(state.reps[owner]["member_id"])
            tally[b["choice"]] += b["weight"]
        base = len(snap["base_members"])
        quorum_met = base > 0 and len(members_voted) / base >= snap["quorum"]
        total = sum(tally.values())
        yes_fraction = (tally["yes"] / total) if total else 0.0
        passed = quorum_met and yes_fraction >= snap["yes_threshold"]
        result = {
            "status": "passed" if passed else "failed",
            "quorum_met": quorum_met,
            "base_size": base,
            "members_voted": len(members_voted),
            "tally": tally,
            "yes_fraction": round(yes_fraction, 6),
            "rules_version": snap["rules_version"],
        }
        return self._emit("vote_closed", {"vote_id": vote_id, "result": result})

    def record_resolution(self, meeting_id: str, item_id: str, vote_id: str,
                          resolution_id: str, text: str,
                          effects: dict | None = None) -> Event:
        state = self._state()
        self._require_meeting_open(state, meeting_id)
        vote = state.votes.get(vote_id)
        if not vote or vote["meeting_id"] != meeting_id or vote["item_id"] != item_id:
            raise GovernanceError("决议必须关联本场会议本议程项的投票")
        if vote["status"] != "closed":
            raise GovernanceError("投票尚未结束，不能形成决议")
        if vote["result"]["status"] != "passed":
            raise GovernanceError("投票未通过，不能记录为决议")
        if resolution_id in state.resolutions:
            raise GovernanceError(f"决议编号已存在: {resolution_id}")
        return self._emit("resolution_recorded", {
            "resolution_id": resolution_id, "meeting_id": meeting_id,
            "item_id": item_id, "vote_id": vote_id, "text": text,
            "effects": effects or {},
        })

    # ------------------------------------------------------------------ #
    # 原文批准与发布确认
    # ------------------------------------------------------------------ #
    def _member_ballot(self, state: RegistryState, vote: dict, member_id: str) -> dict | None:
        for cast_rep, b in vote["ballots"].items():
            owner = b.get("source_rep") or cast_rep
            if state.reps[owner]["member_id"] == member_id:
                return b
        return None

    def approve_original(self, doc_id: str, rev: int, resolution_id: str,
                         by_rep: str) -> Event:
        """原文批准：依据决议，由对决议投赞成的有效代表确认原文修订。"""
        state = self._state()
        rep = self._require_rep(state, by_rep, "原文批准")
        doc = state.documents.get(doc_id)
        if not doc:
            raise GovernanceError(f"未知文件: {doc_id}")
        revision = state.revision(doc_id, rev)
        if not revision:
            raise GovernanceError(f"修订 r{rev} 不存在")
        if revision["language"] != doc["original_language"]:
            raise GovernanceError("只能批准原文修订，翻译稿仅供讨论")
        if rev in doc["approvals"]:
            raise GovernanceError(f"r{rev} 已经完成原文批准，历史签署不可重复")
        resolution = state.resolutions.get(resolution_id)
        if not resolution:
            raise GovernanceError("批准必须引用已记录的决议")
        vote = state.votes[resolution["vote_id"]]
        ballot = self._member_ballot(state, vote, rep["member_id"])
        if not ballot or ballot["choice"] != "yes":
            raise GovernanceError("批准代表所属会员必须对该决议投了赞成票")
        return self._emit("original_approved", {
            "doc_id": doc_id, "rev": rev, "language": revision["language"],
            "resolution_id": resolution_id, "by_rep": by_rep,
        })

    def confirm_publication(self, doc_id: str, rev: int, by_rep: str) -> Event:
        """发布确认：只针对已批准的原文修订；发布后即成为公众入口的生效版本。"""
        state = self._state()
        self._require_rep(state, by_rep, "发布确认")
        doc = state.documents.get(doc_id)
        if not doc:
            raise GovernanceError(f"未知文件: {doc_id}")
        if rev not in doc["approvals"]:
            raise GovernanceError("只有完成原文批准的修订才能发布")
        if any(p["rev"] == rev for p in doc["publications"]):
            raise GovernanceError(f"r{rev} 已经发布确认")
        return self._emit("publish_confirmed", {
            "doc_id": doc_id, "rev": rev, "by_rep": by_rep,
        })
