from __future__ import annotations

import random

import chess

from .base import Engine, EngineResult, SearchLimit


class RandomEngine(Engine):
    def select(self, board: chess.Board, limit: SearchLimit | None = None) -> EngineResult:
        legal_moves = list(board.legal_moves)
        if not legal_moves:
            raise ValueError("No legal moves available")
        move = random.choice(legal_moves)
        return EngineResult(best_move=move, depth=0, nodes=len(legal_moves), pv=(move,))

