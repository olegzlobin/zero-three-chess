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
_INF = 10_000_000
_LMR_MIN_DEPTH = 4
_LMR_BASE_MOVE_INDEX = 6


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
        self._node_budget: Optional[int] = None
        self._nodes_used = 0

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

    def _policy_prior(self, board: chess.Board, move: chess.Move) -> float:
        return 0.0

    def _budget_reached(self) -> bool:
        return self._node_budget is not None and self._nodes_used >= self._node_budget

    def _select_moves_for_node(
        self, board: chess.Board, ordered: list[chess.Move], depth: int
    ) -> list[chess.Move]:
        if not ordered:
            return ordered
        if self._node_budget is None or depth <= 1:
            return ordered
        nodes_left = self._node_budget - self._nodes_used
        if nodes_left <= 0:
            return []
        k = max(4, min(len(ordered), nodes_left // max(8, depth * 4)))
        if k >= len(ordered):
            return ordered

        selected: list[chess.Move] = []
        selected_set: set[chess.Move] = set()
        principal = ordered[0]
        selected.append(principal)
        selected_set.add(principal)
        for move in ordered:
            tactical = board.is_capture(move) or move.promotion is not None or board.gives_check(move)
            if tactical:
                selected.append(move)
                selected_set.add(move)

        remaining = [m for m in ordered if m not in selected_set]
        remaining.sort(key=lambda m: self._policy_prior(board, m), reverse=True)
        for move in remaining:
            if len(selected) >= k:
                break
            selected.append(move)
            selected_set.add(move)

        if not selected:
            return ordered[:k]
        return selected

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

        captures.sort(
            key=lambda m: (_mvv_lva_score(board, m), self._policy_prior(board, m)),
            reverse=True,
        )

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

        rest_quiets.sort(
            key=lambda m: (self._policy_prior(board, m), self._history_score(m)),
            reverse=True,
        )
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
        self._node_budget = limit.nodes if limit is not None else None
        self._nodes_used = 0

        unlimited_depth_by_nodes = limit is not None and limit.depth is None and limit.nodes is not None
        search_depth = limit.depth if limit and limit.depth is not None else self._config.max_depth
        if search_depth <= 0:
            search_depth = 1

        color_sign = 1 if board.turn == chess.WHITE else -1

        score = 0
        best_move: Optional[chess.Move] = None
        best_pv: list[chess.Move] = []
        nodes = 0
        hint: Optional[chess.Move] = None
        reached_depth = 0
        if unlimited_depth_by_nodes:
            d = 1
            while not self._budget_reached():
                score, best_move, n, best_pv = self._negamax_root(
                    board, depth=d, color_sign=color_sign, root_first=hint
                )
                nodes += n
                hint = best_move
                reached_depth = d
                d += 1
        else:
            for d in range(1, search_depth + 1):
                if self._budget_reached():
                    break
                score, best_move, n, best_pv = self._negamax_root(
                    board, depth=d, color_sign=color_sign, root_first=hint
                )
                nodes += n
                hint = best_move
                reached_depth = d

        if best_move is None:
            legal_moves = list(board.legal_moves)
            if not legal_moves:
                raise ValueError("No legal moves available")
            best_move = legal_moves[0]

        return EngineResult(
            best_move=best_move,
            score_cp=score,
            depth=reached_depth,
            nodes=self._nodes_used if self._node_budget is not None else nodes,
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
        alpha = -_INF
        beta = _INF
        best_score = -_INF
        best_move: Optional[chess.Move] = None
        best_pv: list[chess.Move] = []
        nodes = 0

        ordered = self._ordered_moves(board, depth, prefer_first=root_first)
        moves = self._select_moves_for_node(board, ordered, depth)
        for i, move in enumerate(moves):
            if self._budget_reached():
                break
            board.push(move)
            if i == 0:
                score, child_nodes, child_pv = self._negamax(
                    board, depth - 1, -beta, -alpha, -color_sign
                )
                score = -score
            else:
                score, child_nodes, child_pv = self._negamax(
                    board, depth - 1, -alpha - 1, -alpha, -color_sign
                )
                score = -score
                if score > alpha:
                    full_score, extra_nodes, full_pv = self._negamax(
                        board, depth - 1, -beta, -alpha, -color_sign
                    )
                    score = -full_score
                    child_nodes += extra_nodes
                    child_pv = full_pv
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
        if self._budget_reached():
            return self._leaf_eval_score(board, color_sign), nodes, []
        self._nodes_used += 1

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

        in_check = board.is_check()

        best_score = -_INF
        best_pv: list[chess.Move] = []

        ordered = self._ordered_moves(board, depth)
        moves = self._select_moves_for_node(board, ordered, depth)
        for i, move in enumerate(moves):
            if self._budget_reached():
                break
            quiet_for_killer = not board.is_capture(move) and move.promotion is None
            gives_check = board.gives_check(move)

            board.push(move)
            reduction = 0
            if (
                depth >= _LMR_MIN_DEPTH
                and i >= _LMR_BASE_MOVE_INDEX
                and quiet_for_killer
                and not in_check
                and not gives_check
            ):
                reduction = 1
                if depth >= 6 and i >= 12:
                    reduction = 2

            if i == 0:
                score, child_nodes, child_pv = self._negamax(
                    board, depth - 1, -beta, -alpha, -color_sign
                )
                score = -score
            else:
                if reduction > 0:
                    score, child_nodes, child_pv = self._negamax(
                        board,
                        depth - 1 - reduction,
                        -alpha - 1,
                        -alpha,
                        -color_sign,
                    )
                else:
                    score, child_nodes, child_pv = self._negamax(
                        board,
                        depth - 1,
                        -alpha - 1,
                        -alpha,
                        -color_sign,
                    )
                score = -score

                if score > alpha:
                    full_score, extra_nodes, full_pv = self._negamax(
                        board,
                        depth - 1,
                        -beta,
                        -alpha,
                        -color_sign,
                    )
                    score = -full_score
                    child_nodes += extra_nodes
                    child_pv = full_pv

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
