from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import chess

from .game import Game, GameResult
from .player import Player


@dataclass(frozen=True)
class SessionConfig:
    white: Player
    black: Player


class GameSession:
    def __init__(self, config: SessionConfig) -> None:
        self._game = Game()
        self._white = config.white
        self._black = config.black

    @property
    def game(self) -> Game:
        return self._game

    def is_finished(self) -> bool:
        return self._game.is_finished()

    def result(self) -> Optional[GameResult]:
        return self._game.result

    def current_player(self) -> Player:
        return self._white if self._game.turn == chess.WHITE else self._black

    def play_engine_turn_if_applicable(self) -> None:
        if self.is_finished():
            return
        player = self.current_player()
        move = player.choose_move(self._game)
        self._game.make_move(move)

