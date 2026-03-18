from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto
from typing import Iterable, Optional

import chess


class GameResultType(Enum):
    ONGOING = auto()
    CHECKMATE = auto()
    STALEMATE = auto()
    DRAW_MATERIAL = auto()
    DRAW_FIFTY_MOVES = auto()
    DRAW_THREEFOLD = auto()
    RESIGNATION = auto()


@dataclass(frozen=True)
class GameResult:
    result_type: GameResultType
    winner: Optional[chess.Color] = None


class Game:
    def __init__(self) -> None:
        self._board = chess.Board()
        self._result: Optional[GameResult] = None

    @property
    def board(self) -> chess.Board:
        return self._board

    @property
    def turn(self) -> chess.Color:
        return self._board.turn

    @property
    def result(self) -> Optional[GameResult]:
        if self._result is not None:
            return self._result

        if self._board.is_checkmate():
            winner = not self._board.turn
            return GameResult(GameResultType.CHECKMATE, winner=winner)

        if self._board.is_stalemate():
            return GameResult(GameResultType.STALEMATE)

        if self._board.is_insufficient_material():
            return GameResult(GameResultType.DRAW_MATERIAL)

        if self._board.can_claim_fifty_moves():
            return GameResult(GameResultType.DRAW_FIFTY_MOVES)

        if self._board.can_claim_threefold_repetition():
            return GameResult(GameResultType.DRAW_THREEFOLD)

        return None

    def is_finished(self) -> bool:
        return self.result is not None

    def legal_moves(self) -> Iterable[chess.Move]:
        return self._board.legal_moves

    def make_move(self, move: chess.Move) -> None:
        if move not in self._board.legal_moves:
            raise ValueError("Illegal move")
        self._board.push(move)

