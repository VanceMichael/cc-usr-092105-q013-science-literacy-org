"""只追加事件存储。

存储为 JSONL 文件，每行一个事件：``seq``（全库单调序号）、``at``（UTC）、
``type``、``data``、``cmd``（命令去重键，可选）。写入在进程间用文件锁串行化，
因此多人同时提交联合编辑时序号仍然连续；重放按 seq 排序，任何历史事件
都不会被改写，保证已经承担的责任和历史签署可追溯。
"""

from __future__ import annotations

import fcntl
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterator

from .clock import now, to_text, parse_moment
from datetime import datetime


@dataclass(frozen=True)
class Event:
    seq: int
    at: datetime
    type: str
    data: dict
    cmd: str | None = None

    def to_json(self) -> dict:
        return {
            "seq": self.seq,
            "at": to_text(self.at),
            "type": self.type,
            "data": self.data,
            **({"cmd": self.cmd} if self.cmd else {}),
        }

    @classmethod
    def from_json(cls, raw: dict) -> "Event":
        return cls(
            seq=raw["seq"],
            at=parse_moment(raw["at"]),
            type=raw["type"],
            data=raw["data"],
            cmd=raw.get("cmd"),
        )


class EventStore:
    """JSONL 事件存储。

    适合单节点后台与演示；同一把 ``.lock`` 文件保证多进程写入安全。
    """

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock_path = self.path.with_suffix(self.path.suffix + ".lock")

    def _read_all(self) -> list[Event]:
        if not self.path.exists():
            return []
        events: list[Event] = []
        with self.path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    events.append(Event.from_json(json.loads(line)))
        return events

    def append(
        self,
        event_type: str,
        data: dict,
        *,
        at: datetime | None = None,
        cmd: str | None = None,
    ) -> Event:
        """追加一个事件；相同 ``cmd`` 去重键的提交会被幂等忽略。"""
        with self._lock_path.open("a+") as lock_fh:
            fcntl.flock(lock_fh, fcntl.LOCK_EX)
            existing = self._read_all()
            if cmd is not None:
                for ev in existing:
                    if ev.cmd == cmd:
                        # 同一命令重放：返回已落库的事件，不产生重复责任。
                        return ev
            seq = (existing[-1].seq + 1) if existing else 1
            event = Event(seq=seq, at=at or now(), type=event_type, data=data, cmd=cmd)
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(event.to_json(), ensure_ascii=False) + "\n")
                fh.flush()
                os.fsync(fh.fileno())
            return event

    def replay(self) -> list[Event]:
        """按序号返回全部事件。"""
        return sorted(self._read_all(), key=lambda e: e.seq)

    def iter_events(self) -> Iterator[Event]:
        yield from self.replay()

    def seen_cmds(self) -> frozenset[str]:
        return frozenset(e.cmd for e in self.replay() if e.cmd)
