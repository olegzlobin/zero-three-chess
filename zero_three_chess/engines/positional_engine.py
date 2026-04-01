from __future__ import annotations

from typing import Optional

import chess

from .material_engine import PIECE_VALUES
from .negamax_search import NegamaxSearchConfig, NegamaxSearchEngine

PositionalEngineConfig = NegamaxSearchConfig

# Материал: PIECE_VALUES в material_engine (пешка = 100 с.п.); в итог идёт без масштаба.

# Вес ранга пешки (0–7) и полуза центр в сырой сумме pawn_activity до умножения на _PAWN_ACTIVITY_MUL.
_PAWN_RANK_WEIGHT = 3
# Бонус за вертикали d/e и c/f в сырой pawn_activity.
_PAWN_FILE_BONUS_CENTER = 5
_PAWN_FILE_BONUS_WIDE = 3

# Множитель сырой pawn_activity при сложении с остальным позиционным блоком.
_PAWN_ACTIVITY_MUL = 3

# Делитель мобильности: вклад = sum(min(атаки, потолок)) // _MOBILITY_DIV; больше делитель — слабее мобильность.
_MOBILITY_DIV = 22

# Потолки числа атакованных полей по типу фигуры (ограничивают вклад ферзя и т.д.).
_MOBILITY_CAP_KNIGHT = 6
_MOBILITY_CAP_BISHOP = 8
_MOBILITY_CAP_ROOK = 9
_MOBILITY_CAP_QUEEN = 18

# Доля суммы PST (конь/слон/ладья/ферзь) перед общим позиционным масштабом.
_PST_SCALE_NUM = 1
_PST_SCALE_DEN = 2

# Общий масштаб всего позиционного (не материала): (активность + PST + мобильность + структура + укрытие) * NUM // DEN.
_POSITIONAL_NUM = 1
_POSITIONAL_DEN = 3

# Бонус за двух слонов у одной стороны.
_BISHOP_PAIR = 9

# Штраф за лишние пешки на одной вертикали (за каждую сверх первой).
_DOUBLE_PAWN = 10
# Штраф за изолированную пешку (нет своих на соседних вертикалях).
_ISOLATED_PAWN = 8

# Ладья на открытой / полуоткрытой вертикали (нет своих пешек на линии; semi — есть чужие).
_ROOK_OPEN = 8
_ROOK_SEMI = 4

# За каждую свою пешку на поле «впереди короля» в зоне укрытия (три клетки по горизонтали).
_SHELTER_PER_PAWN = 3

# Дебют: штраф за коня/слона, всё ещё стоящих на своей 1-й/8-й горизонтали (мотивация развить фигуры).
_OPENING_MAX_FULLMOVE = 14
_BACK_RANK_MINOR_PENALTY = 14

# Рокировка: штраф за долгое стояние на e1/e8 при ещё доступной рокировке; бонус за короля на g/c после типичной рокировки.
_CASTLE_PRESS_FULLMOVE = 18
_E1_UNCASTLED_PENALTY = 12
_KING_CASTLED_BONUS = 8
_CASTLED_BONUS_FULLMOVE = 22

_KNIGHT_PST: tuple[tuple[int, ...], ...] = (
    (-14, -10, -8, -6, -6, -8, -10, -14),
    (-10, -4, 0, 0, 0, 0, -4, -10),
    (-8, 0, 4, 6, 6, 4, 0, -8),
    (-8, 2, 6, 8, 8, 6, 2, -8),
    (-8, 2, 6, 8, 8, 6, 2, -8),
    (-8, 0, 4, 6, 6, 4, 0, -8),
    (-10, -4, 0, 0, 0, 0, -4, -10),
    (-14, -10, -8, -6, -6, -8, -10, -14),
)

_BISHOP_PST: tuple[tuple[int, ...], ...] = (
    (-12, -8, -8, -8, -8, -8, -8, -12),
    (-8, 2, 4, 4, 4, 4, 2, -8),
    (-8, 4, 6, 6, 6, 6, 4, -8),
    (-8, 4, 6, 8, 8, 6, 4, -8),
    (-8, 4, 6, 8, 8, 6, 4, -8),
    (-8, 4, 6, 6, 6, 6, 4, -8),
    (-8, 2, 4, 4, 4, 4, 2, -8),
    (-12, -8, -8, -8, -8, -8, -8, -12),
)

_ROOK_PST: tuple[tuple[int, ...], ...] = (
    (0, 0, 0, 2, 2, 0, 0, 0),
    (-4, 0, 0, 0, 0, 0, 0, -4),
    (-4, 0, 0, 0, 0, 0, 0, -4),
    (-4, 0, 0, 0, 0, 0, 0, -4),
    (-4, 0, 0, 0, 0, 0, 0, -4),
    (-2, 0, 0, 2, 2, 0, 0, -2),
    (4, 6, 6, 6, 6, 6, 6, 4),
    (0, 0, 0, 0, 0, 0, 0, 0),
)

_QUEEN_PST: tuple[tuple[int, ...], ...] = (
    (-10, -6, -6, -4, -4, -6, -6, -10),
    (-8, 0, 2, 2, 2, 2, 0, -8),
    (-8, 2, 4, 4, 4, 4, 2, -8),
    (-6, 2, 4, 6, 6, 4, 2, -6),
    (-6, 2, 4, 6, 6, 4, 2, -6),
    (-8, 2, 4, 4, 4, 4, 2, -8),
    (-8, 0, 2, 2, 2, 2, 0, -8),
    (-10, -6, -6, -4, -4, -6, -6, -10),
)


def _pst(
    table: tuple[tuple[int, ...], ...],
    square: chess.Square,
    color: chess.Color,
) -> int:
    rank = chess.square_rank(square)
    file = chess.square_file(square)
    if color == chess.BLACK:
        rank = 7 - rank
    return table[rank][file]


def _mobility_cap(piece_type: int) -> int:
    if piece_type == chess.KNIGHT:
        return _MOBILITY_CAP_KNIGHT
    if piece_type == chess.BISHOP:
        return _MOBILITY_CAP_BISHOP
    if piece_type == chess.ROOK:
        return _MOBILITY_CAP_ROOK
    if piece_type == chess.QUEEN:
        return _MOBILITY_CAP_QUEEN
    return 0


def _king_shelter_delta(board: chess.Board) -> int:
    w = 0
    b = 0
    wk = board.king(chess.WHITE)
    bk = board.king(chess.BLACK)
    if wk is not None:
        wr = chess.square_rank(wk)
        wf = chess.square_file(wk)
        if wr < 7:
            for df in (-1, 0, 1):
                ff = wf + df
                if 0 <= ff <= 7:
                    sq = chess.square(ff, wr + 1)
                    pc = board.piece_at(sq)
                    if pc is not None and pc.piece_type == chess.PAWN and pc.color == chess.WHITE:
                        w += _SHELTER_PER_PAWN
    if bk is not None:
        br = chess.square_rank(bk)
        bf = chess.square_file(bk)
        if br > 0:
            for df in (-1, 0, 1):
                ff = bf + df
                if 0 <= ff <= 7:
                    sq = chess.square(ff, br - 1)
                    pc = board.piece_at(sq)
                    if pc is not None and pc.piece_type == chess.PAWN and pc.color == chess.BLACK:
                        b += _SHELTER_PER_PAWN
    return w - b


def _opening_minor_development_delta(board: chess.Board) -> int:
    if board.fullmove_number > _OPENING_MAX_FULLMOVE:
        return 0
    d = 0
    for square, piece in board.piece_map().items():
        pt = piece.piece_type
        if pt != chess.KNIGHT and pt != chess.BISHOP:
            continue
        r = chess.square_rank(square)
        if piece.color == chess.WHITE:
            if r == 0:
                d -= _BACK_RANK_MINOR_PENALTY
        elif r == 7:
            d += _BACK_RANK_MINOR_PENALTY
    return d


def _castling_delta(board: chess.Board) -> int:
    d = 0
    fm = board.fullmove_number
    wk = board.king(chess.WHITE)
    bk = board.king(chess.BLACK)
    if wk is not None:
        if wk == chess.E1:
            if fm <= _CASTLE_PRESS_FULLMOVE and board.has_castling_rights(chess.WHITE):
                d -= _E1_UNCASTLED_PENALTY
        elif wk in (chess.G1, chess.C1) and fm <= _CASTLED_BONUS_FULLMOVE:
            d += _KING_CASTLED_BONUS
    if bk is not None:
        if bk == chess.E8:
            if fm <= _CASTLE_PRESS_FULLMOVE and board.has_castling_rights(chess.BLACK):
                d += _E1_UNCASTLED_PENALTY
        elif bk in (chess.G8, chess.C8) and fm <= _CASTLED_BONUS_FULLMOVE:
            d -= _KING_CASTLED_BONUS
    return d


class PositionalEngine(NegamaxSearchEngine):
    def __init__(self, config: Optional[NegamaxSearchConfig] = None) -> None:
        # max_depth по умолчанию для позиционного движка, если в SearchLimit не задана depth.
        super().__init__(config or NegamaxSearchConfig(max_depth=8))

    def _evaluate(self, board: chess.Board) -> int:
        pw = [0] * 8
        pb = [0] * 8
        for square, piece in board.piece_map().items():
            if piece.piece_type != chess.PAWN:
                continue
            f = chess.square_file(square)
            if piece.color == chess.WHITE:
                pw[f] += 1
            else:
                pb[f] += 1

        material = 0
        pawn_activity = 0
        pst = 0
        mobility = 0
        structure = 0
        bishops_w = 0
        bishops_b = 0

        for square, piece in board.piece_map().items():
            pt = piece.piece_type
            value = PIECE_VALUES[pt]
            sign = 1 if piece.color == chess.WHITE else -1
            material += sign * value

            if pt == chess.PAWN:
                rank = chess.square_rank(square)
                file = chess.square_file(square)
                center_bonus = 0
                if file in (3, 4):
                    center_bonus = _PAWN_FILE_BONUS_CENTER
                elif file in (2, 5):
                    center_bonus = _PAWN_FILE_BONUS_WIDE
                if piece.color == chess.WHITE:
                    pawn_activity += rank * _PAWN_RANK_WEIGHT + center_bonus
                else:
                    pawn_activity -= (7 - rank) * _PAWN_RANK_WEIGHT + center_bonus
                continue

            if pt == chess.KNIGHT:
                pst += sign * _pst(_KNIGHT_PST, square, piece.color)
            elif pt == chess.BISHOP:
                pst += sign * _pst(_BISHOP_PST, square, piece.color)
                if piece.color == chess.WHITE:
                    bishops_w += 1
                else:
                    bishops_b += 1
            elif pt == chess.ROOK:
                pst += sign * _pst(_ROOK_PST, square, piece.color)
                f = chess.square_file(square)
                if piece.color == chess.WHITE:
                    if pw[f] == 0:
                        structure += _ROOK_OPEN if pb[f] == 0 else _ROOK_SEMI
                else:
                    if pb[f] == 0:
                        structure -= _ROOK_OPEN if pw[f] == 0 else _ROOK_SEMI
            elif pt == chess.QUEEN:
                pst += sign * _pst(_QUEEN_PST, square, piece.color)

            cap = _mobility_cap(pt)
            if cap:
                mobility += sign * min(len(board.attacks(square)), cap)

        if bishops_w >= 2:
            structure += _BISHOP_PAIR
        if bishops_b >= 2:
            structure -= _BISHOP_PAIR

        for f in range(8):
            if pw[f] > 1:
                structure -= _DOUBLE_PAWN * (pw[f] - 1)
            if pb[f] > 1:
                structure += _DOUBLE_PAWN * (pb[f] - 1)

        for f in range(8):
            if pw[f] == 0:
                continue
            iso = True
            if f > 0 and pw[f - 1] > 0:
                iso = False
            if f < 7 and pw[f + 1] > 0:
                iso = False
            if iso:
                structure -= _ISOLATED_PAWN

        for f in range(8):
            if pb[f] == 0:
                continue
            iso = True
            if f > 0 and pb[f - 1] > 0:
                iso = False
            if f < 7 and pb[f + 1] > 0:
                iso = False
            if iso:
                structure += _ISOLATED_PAWN

        pst_scaled = (pst * _PST_SCALE_NUM) // _PST_SCALE_DEN
        positional = (
            pawn_activity * _PAWN_ACTIVITY_MUL
            + pst_scaled
            + mobility // _MOBILITY_DIV
            + structure
            + _king_shelter_delta(board)
            + _opening_minor_development_delta(board)
            + _castling_delta(board)
        )
        positional = (positional * _POSITIONAL_NUM) // _POSITIONAL_DEN

        return material + positional


def positional_engine(config: Optional[NegamaxSearchConfig] = None) -> PositionalEngine:
    return PositionalEngine(config)
