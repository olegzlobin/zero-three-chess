from __future__ import annotations

import sys

import chess

from zero_three_chess.core.game import Game
from zero_three_chess.core.player import EnginePlayer, Player
from zero_three_chess.engines.random_engine import RandomEngine


class HumanCliPlayer(Player):
    def choose_move(self, game: Game) -> chess.Move:
        board = game.board
        while True:
            print(board)
            user_input = input("Your move (UCI, e.g. e2e4 or 'quit'): ").strip()

            if user_input.lower() in {"q", "quit", "exit"}:
                print("Exiting.")
                sys.exit(0)

            try:
                move = chess.Move.from_uci(user_input)
            except ValueError:
                print("Cannot parse move, try again.")
                continue

            if move not in board.legal_moves:
                print("Illegal move, try again.")
                continue

            return move


def run_human_vs_random() -> None:
    print("Zero-Three Chess: human vs RandomEngine")

    game = Game()
    human_color = chess.WHITE

    human = HumanCliPlayer()
    engine = EnginePlayer(RandomEngine())

    while not game.is_finished():
        if game.turn == human_color:
            move = human.choose_move(game)
        else:
            move = engine.choose_move(game)
            print(f"Engine plays: {move.uci()}")

        game.make_move(move)

    result = game.result
    print(game.board)
    if result is None:
        print("Game finished with unknown result.")
        return

    if result.winner is None:
        print(f"Game drawn: {result.result_type.name}")
    else:
        color_name = "White" if result.winner else "Black"
        print(f"{color_name} wins by {result.result_type.name}.")


if __name__ == "__main__":
    run_human_vs_random()

