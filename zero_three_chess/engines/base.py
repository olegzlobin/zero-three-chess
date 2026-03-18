from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Protocol

import chess


@dataclass(frozen=True)
class SearchLimit:
    depth: Optional[int] = None
    time_ms: Optional[int] = None
    nodes: Optional[int] = None


@dataclass(frozen=True)
class EngineResult:
    best_move: chess.Move
    score_cp: Optional[int] = None
    mate_in: Optional[int] = None
    depth: Optional[int] = None
    nodes: Optional[int] = None
    pv: tuple[chess.Move, ...] = ()


class Engine(Protocol):
    def select(self, board: chess.Board, limit: SearchLimit | None = None) -> EngineResult:
        ...

