from __future__ import annotations

from typing import Callable, Optional

import chess

from .negamax_search import NegamaxSearchConfig, NegamaxSearchEngine


PIECE_VALUES: dict[int, int] = {
    chess.PAWN: 100,
    chess.KNIGHT: 320,
    chess.BISHOP: 330,
    chess.ROOK: 500,
    chess.QUEEN: 900,
    chess.KING: 0,
}

MaterialEngineConfig = NegamaxSearchConfig


class MaterialEngine(NegamaxSearchEngine):
    def __init__(
        self,
        config: Optional[NegamaxSearchConfig] = None,
        evaluator: Optional[Callable[[chess.Board], int]] = None,
    ) -> None:
        super().__init__(config or NegamaxSearchConfig())
        self._evaluator_override = evaluator

    def _evaluate(self, board: chess.Board) -> int:
        if self._evaluator_override is not None:
            return self._evaluator_override(board)
        return self._evaluate_material(board)

    def _evaluate_material(self, board: chess.Board) -> int:
        material = 0
        pawn_activity = 0

        for square, piece in board.piece_map().items():
            value = PIECE_VALUES[piece.piece_type]
            if piece.color == chess.WHITE:
                material += value
            else:
                material -= value

            if piece.piece_type == chess.PAWN:
                rank = chess.square_rank(square)
                file = chess.square_file(square)

                center_bonus = 0
                if file in (3, 4):
                    center_bonus = 2
                elif file in (2, 5):
                    center_bonus = 1

                if piece.color == chess.WHITE:
                    pawn_activity += rank + center_bonus
                else:
                    pawn_activity -= (7 - rank) + center_bonus

        return material + pawn_activity * 2
