from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Protocol

import chess

from .game import Game
from zero_three_chess.engines.base import Engine, SearchLimit


class Player(ABC):
    @abstractmethod
    def choose_move(self, game: Game) -> chess.Move:
        raise NotImplementedError


class EngineLike(Protocol):
    def select(self, board: chess.Board, limit: SearchLimit | None = None) -> chess.Move:
        ...


class EnginePlayer(Player):
    def __init__(self, engine: Engine, limit: SearchLimit | None = None) -> None:
        self._engine = engine
        self._limit = limit or SearchLimit(depth=1)

    def choose_move(self, game: Game) -> chess.Move:
        result = self._engine.select(game.board, self._limit)
        return result.best_move

