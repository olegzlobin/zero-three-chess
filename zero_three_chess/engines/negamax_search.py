from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional

import chess

from .base import Engine, EngineResult, SearchLimit

_ORDERING_PIECE_VALUES: dict[int, int] = {
    chess.PAWN: 100,
    chess.KNIGHT: 320,
    chess.BISHOP: 330,
    chess.ROOK: 500,
    chess.QUEEN: 900,
    chess.KING: 0,
}

_MAX_KILLER_DEPTH = 64


def _board_tt_key(board: chess.Board) -> int:
    if hasattr(board, "zobrist_hash"):
        z = board.zobrist_hash
        return int(z() if callable(z) else z)
    from chess.polyglot import zobrist_hash

    return int(zobrist_hash(board))


def _material_balance_white(board: chess.Board) -> int:
    total = 0
    for _sq, piece in board.piece_map().items():
        v = _ORDERING_PIECE_VALUES.get(piece.piece_type, 0)
        if piece.color == chess.WHITE:
            total += v
        else:
            total -= v
    return total


def _mvv_lva_score(board: chess.Board, move: chess.Move) -> int:
    victim = board.piece_at(move.to_square)
    attacker = board.piece_at(move.from_square)
    if victim is None or attacker is None:
        return 0
    vv = _ORDERING_PIECE_VALUES.get(victim.piece_type, 0)
    av = _ORDERING_PIECE_VALUES.get(attacker.piece_type, 0)
    return vv * 256 - av


@dataclass(frozen=True)
class NegamaxSearchConfig:
    max_depth: int = 5


class NegamaxSearchEngine(Engine, ABC):
    def __init__(self, config: NegamaxSearchConfig) -> None:
        self._config = config
        self._tt: dict[tuple[int, int], tuple[int, int, list[chess.Move]]] = {}
        self._killers: list[list[Optional[chess.Move]]] = [[None, None] for _ in range(_MAX_KILLER_DEPTH)]
        self._history: dict[tuple[int, int], int] = {}

    @abstractmethod
    def _evaluate(self, board: chess.Board) -> int:
        pass

    def _reset_move_ordering(self) -> None:
        for i in range(_MAX_KILLER_DEPTH):
            self._killers[i][0] = None
            self._killers[i][1] = None
        self._history.clear()

    def _store_killer(self, depth: int, move: chess.Move) -> None:
        if depth <= 0 or depth >= _MAX_KILLER_DEPTH:
            return
        slot = self._killers[depth]
        if slot[0] == move:
            return
        slot[1] = slot[0]
        slot[0] = move

    def _history_score(self, move: chess.Move) -> int:
        return self._history.get((move.from_square, move.to_square), 0)

    def _update_history(self, move: chess.Move, depth: int) -> None:
        key = (move.from_square, move.to_square)
        self._history[key] = self._history.get(key, 0) + depth * depth

    def _ordered_moves(
        self,
        board: chess.Board,
        depth: int,
        prefer_first: Optional[chess.Move] = None,
    ) -> list[chess.Move]:
        legal = list(board.legal_moves)
        ordered: list[chess.Move] = []

        captures: list[chess.Move] = []
        quiets: list[chess.Move] = []
        for m in legal:
            if board.is_capture(m):
                captures.append(m)
            else:
                quiets.append(m)

        captures.sort(key=lambda m: _mvv_lva_score(board, m), reverse=True)

        killer_depth = depth
        if 0 < killer_depth < _MAX_KILLER_DEPTH:
            k0, k1 = self._killers[killer_depth][0], self._killers[killer_depth][1]
        else:
            k0, k1 = None, None

        killer_quiets: list[chess.Move] = []
        rest_quiets: list[chess.Move] = []
        for m in quiets:
            if k0 is not None and m == k0:
                killer_quiets.insert(0, m)
            elif k1 is not None and m == k1:
                killer_quiets.append(m)
            else:
                rest_quiets.append(m)

        rest_quiets.sort(key=lambda m: self._history_score(m), reverse=True)
        ordered.extend(captures)
        ordered.extend(killer_quiets)
        ordered.extend(rest_quiets)
        if prefer_first is not None:
            for i, m in enumerate(ordered):
                if m == prefer_first:
                    ordered = [m] + ordered[:i] + ordered[i + 1 :]
                    break
        return ordered

    def select(self, board: chess.Board, limit: SearchLimit | None = None) -> EngineResult:
        self._reset_move_ordering()
        self._tt.clear()

        search_depth = limit.depth if limit and limit.depth is not None else self._config.max_depth
        if search_depth <= 0:
            search_depth = 1

        color_sign = 1 if board.turn == chess.WHITE else -1

        score = 0
        best_move: Optional[chess.Move] = None
        best_pv: list[chess.Move] = []
        nodes = 0
        hint: Optional[chess.Move] = None
        for d in range(1, search_depth + 1):
            score, best_move, n, best_pv = self._negamax_root(
                board, depth=d, color_sign=color_sign, root_first=hint
            )
            nodes += n
            hint = best_move

        if best_move is None:
            legal_moves = list(board.legal_moves)
            if not legal_moves:
                raise ValueError("No legal moves available")
            best_move = legal_moves[0]

        return EngineResult(
            best_move=best_move,
            score_cp=score,
            depth=search_depth,
            nodes=nodes,
            pv=tuple(best_pv),
        )

    def _leaf_eval_score(self, board: chess.Board, color_sign: int) -> int:
        outcome = board.outcome()
        if outcome is not None:
            if outcome.winner is None:
                return 0
            if (outcome.winner == chess.WHITE and color_sign == 1) or (
                outcome.winner == chess.BLACK and color_sign == -1
            ):
                return 10_000
            return -10_000
        if hasattr(board, "is_repetition") and board.is_repetition(2):
            mat = _material_balance_white(board)
            if abs(mat) > 50:
                if board.is_repetition(3):
                    return (-mat) * color_sign
                extra = -(mat // 2) if mat > 0 else (-mat) // 2
                return (self._evaluate(board) + extra) * color_sign
        return self._evaluate(board) * color_sign

    def _negamax_root(
        self,
        board: chess.Board,
        depth: int,
        color_sign: int,
        root_first: Optional[chess.Move] = None,
    ) -> tuple[int, Optional[chess.Move], int, list[chess.Move]]:
        alpha = -10_000_000
        beta = 10_000_000
        best_score = -10_000_000
        best_move: Optional[chess.Move] = None
        best_pv: list[chess.Move] = []
        nodes = 0

        for move in self._ordered_moves(board, depth, prefer_first=root_first):
            board.push(move)
            score, child_nodes, child_pv = self._negamax(board, depth - 1, -beta, -alpha, -color_sign)
            score = -score
            nodes += child_nodes + 1
            board.pop()

            if score > best_score:
                best_score = score
                best_move = move
                best_pv = [move] + child_pv

            if score > alpha:
                alpha = score

        if best_move is None:
            return self._leaf_eval_score(board, color_sign), None, nodes, []

        return best_score, best_move, nodes, best_pv

    def _negamax(
        self,
        board: chess.Board,
        depth: int,
        alpha: int,
        beta: int,
        color_sign: int,
    ) -> tuple[int, int, list[chess.Move]]:
        nodes = 0

        if (
            depth == 0
            or board.is_game_over()
            or (hasattr(board, "is_repetition") and board.is_repetition(3))
        ):
            return self._leaf_eval_score(board, color_sign), 1, []

        tt_key = (_board_tt_key(board), depth)
        cached = self._tt.get(tt_key)
        if cached is not None:
            return cached

        best_score = -10_000_000
        best_pv: list[chess.Move] = []

        for move in self._ordered_moves(board, depth):
            quiet_for_killer = not board.is_capture(move) and move.promotion is None
            board.push(move)
            score, child_nodes, child_pv = self._negamax(board, depth - 1, -beta, -alpha, -color_sign)
            score = -score
            nodes += child_nodes + 1
            board.pop()

            if score > best_score:
                best_score = score
                best_pv = [move] + child_pv

            if score > alpha:
                alpha = score
            if alpha >= beta:
                if quiet_for_killer:
                    self._store_killer(depth, move)
                    self._update_history(move, depth)
                break

        result = (best_score, nodes, best_pv)
        self._tt[tt_key] = result
        return result
