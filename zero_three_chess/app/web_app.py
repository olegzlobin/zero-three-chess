from __future__ import annotations

import json
import os
import threading
import time
import webbrowser
from dataclasses import dataclass
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from mimetypes import guess_type
from typing import Optional
from urllib.parse import urlparse

import chess

from zero_three_chess.core.game import Game, GameResultType
from zero_three_chess.core.player import EnginePlayer
from zero_three_chess.engines.random_engine import RandomEngine
from zero_three_chess.engines.material_engine import MaterialEngine, MaterialEngineConfig
from zero_three_chess.engines.positional_engine import positional_engine


UNICODE_PIECES = {
    chess.PAWN: {chess.WHITE: "♙", chess.BLACK: "♟"},
    chess.KNIGHT: {chess.WHITE: "♘", chess.BLACK: "♞"},
    chess.BISHOP: {chess.WHITE: "♗", chess.BLACK: "♝"},
    chess.ROOK: {chess.WHITE: "♖", chess.BLACK: "♜"},
    chess.QUEEN: {chess.WHITE: "♕", chess.BLACK: "♛"},
    chess.KING: {chess.WHITE: "♔", chess.BLACK: "♚"},
}


@dataclass
class AppState:
    game: Game
    white_kind: str  # "human" or engine id
    black_kind: str  # "human" or engine id
    white_engine: EnginePlayer
    black_engine: EnginePlayer
    selected_square: Optional[chess.Square]
    lock: threading.Lock
    last_seen_ts: float
    shutdown_after_s: int
    last_eval_cp: Optional[int]
    last_eval_depth: Optional[int]
    last_eval_nodes: Optional[int]
    search_depth: int
    search_nodes: Optional[int]


def _engine_player_for_color(app: AppState, color: chess.Color) -> EnginePlayer:
    return app.white_engine if color == chess.WHITE else app.black_engine


def _side_kind(app: AppState, color: chess.Color) -> str:
    return app.white_kind if color == chess.WHITE else app.black_kind


def _player_header_name(kind: str) -> str:
    return {
        "human": "Human",
        "random": "Random",
        "material": "Material",
        "positional": "Positional",
    }.get(kind, kind)


def _pgn_result_header(app: AppState) -> str:
    r = app.game.result
    if r is None:
        return "*"
    if r.winner is None:
        return "1/2-1/2"
    if r.winner == chess.WHITE:
        return "1-0"
    return "0-1"


def _build_pgn(app: AppState) -> str:
    import chess.pgn

    game = chess.pgn.Game()
    game.headers["Event"] = "Zero-Three Chess"
    game.headers["Site"] = "?"
    game.headers["Round"] = "-"
    game.headers["Date"] = datetime.now(timezone.utc).strftime("%Y.%m.%d")
    game.headers["White"] = _player_header_name(app.white_kind)
    game.headers["Black"] = _player_header_name(app.black_kind)
    game.headers["Result"] = _pgn_result_header(app)

    node = game
    for move in app.game.board.move_stack:
        node = node.add_variation(move)

    return str(game)


def _pieces_payload(board: chess.Board) -> dict[str, dict[str, str]]:
    pieces: dict[str, dict[str, str]] = {}
    for square in chess.SQUARES:
        piece = board.piece_at(square)
        if piece is None:
            continue
        name = chess.square_name(square)
        code_color = "w" if piece.color == chess.WHITE else "b"
        type_map = {
            chess.KING: "K",
            chess.QUEEN: "Q",
            chess.ROOK: "R",
            chess.BISHOP: "B",
            chess.KNIGHT: "N",
            chess.PAWN: "P",
        }
        code_type = type_map[piece.piece_type]
        pieces[name] = {
            "glyph": UNICODE_PIECES[piece.piece_type][piece.color],
            "code": f"{code_color}{code_type}",
        }
    return pieces


def _state_payload(app: AppState) -> dict:
    board = app.game.board
    pieces = _pieces_payload(board)

    turn_color = "white" if board.turn == chess.WHITE else "black"
    turn_text = "Белые" if board.turn == chess.WHITE else "Чёрные"

    if not app.game.is_finished():
        status_text = "Игра продолжается"
    else:
        result = app.game.result
        if result is None:
            status_text = "Партия окончена."
        elif result.winner is None:
            status_text = f"Ничья ({result.result_type.name})"
        else:
            winner_name = "Белые" if result.winner == chess.WHITE else "Чёрные"
            if result.result_type == GameResultType.CHECKMATE:
                status_text = f"Мат. Победа: {winner_name}"
            else:
                status_text = f"Победа: {winner_name} ({result.result_type.name})"

    legal_targets: list[str] = []
    if app.selected_square is not None:
        for move in app.game.legal_moves():
            if move.from_square == app.selected_square:
                legal_targets.append(chess.square_name(move.to_square))

    last_move_info: dict[str, str] | None = None
    if board.move_stack:
        last = board.move_stack[-1]
        last_move_info = {
            "from": chess.square_name(last.from_square),
            "to": chess.square_name(last.to_square),
        }

    return {
        "pieces": pieces,
        "turn_text": f"Ход: {turn_text}",
        "status_text": status_text,
        "selected": chess.square_name(app.selected_square) if app.selected_square is not None else None,
        "finished": app.game.is_finished(),
        "legal_targets": legal_targets,
        "turn_color": turn_color,
        "white_kind": app.white_kind,
        "black_kind": app.black_kind,
        "last_move": last_move_info,
        "eval_cp": app.last_eval_cp,
        "eval_depth": app.last_eval_depth,
        "eval_nodes": app.last_eval_nodes,
        "search_depth": app.search_depth,
        "search_nodes": app.search_nodes,
    }


def _play_engine_move_once(app: AppState) -> None:
    from zero_three_chess.engines.base import SearchLimit

    with app.lock:
        if app.game.is_finished():
            return
        color = app.game.turn
        if _side_kind(app, color) == "human":
            return
        snap_fen = app.game.board.fen()
        search_depth = app.search_depth
        search_nodes = app.search_nodes
        engine_player = _engine_player_for_color(app, color)
        board_copy = app.game.board.copy(stack=True)
    if search_nodes is not None and search_nodes > 0:
        limit = SearchLimit(nodes=search_nodes)
    else:
        limit = SearchLimit(depth=search_depth)
    result = engine_player._engine.select(board_copy, limit)
    move = result.best_move

    with app.lock:
        if app.game.is_finished():
            return
        if app.game.turn != color:
            return
        if app.game.board.fen() != snap_fen:
            return
        if move not in app.game.board.legal_moves:
            return
        app.game.make_move(move)

        score_cp = result.score_cp
        if score_cp is not None:
            if color == chess.WHITE:
                app.last_eval_cp = score_cp
            else:
                app.last_eval_cp = -score_cp
        else:
            app.last_eval_cp = None

        app.last_eval_depth = result.depth
        app.last_eval_nodes = result.nodes


def _auto_play_engines(app: AppState, max_plies: int = 1) -> None:
    for _ in range(max_plies):
        if app.game.is_finished():
            return
        turn_before = app.game.turn
        _play_engine_move_once(app)
        if app.game.is_finished():
            return
        if app.game.turn == turn_before:
            return
        if _side_kind(app, app.game.turn) == "human":
            return


class Handler(BaseHTTPRequestHandler):
    server: "ChessServer"

    def log_message(self, format: str, *args) -> None:
        return

    @property
    def _app(self) -> AppState:
        return self.server.app_state

    def _send(self, status: int, content_type: str, body: bytes) -> None:
        self.send_response(status)
        self.send_header("content-type", content_type)
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self._send(status, "application/json; charset=utf-8", body)

    def _send_text(self, status: int, text: str) -> None:
        self._send(status, "text/plain; charset=utf-8", text.encode("utf-8"))

    def _read_json(self) -> dict:
        length = int(self.headers.get("content-length", "0"))
        raw = self.rfile.read(length) if length > 0 else b"{}"
        try:
            value = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            raise ValueError("Некорректный JSON")
        if not isinstance(value, dict):
            raise ValueError("Некорректный JSON")
        return value

    def _serve_static_file(self, rel_path: str) -> bool:
        base = os.path.dirname(__file__)
        fs_path = os.path.join(base, "static", rel_path)
        if not os.path.isfile(fs_path):
            return False
        ctype, _ = guess_type(fs_path)
        if ctype is None:
            ctype = "application/octet-stream"
        with open(fs_path, "rb") as f:
            data = f.read()
        self._send(HTTPStatus.OK, ctype, data)
        return True

    def _handle_get_index(self) -> None:
        if not self._serve_static_file("index.html"):
            self._send_text(HTTPStatus.INTERNAL_SERVER_ERROR, "index.html not found")

    def _handle_get_state(self) -> None:
        with self._app.lock:
            self._app.last_seen_ts = time.time()
        _auto_play_engines(self._app, max_plies=1)
        with self._app.lock:
            self._send_json(HTTPStatus.OK, _state_payload(self._app))

    def _handle_get_ping(self) -> None:
        with self._app.lock:
            self._app.last_seen_ts = time.time()
        self._send_json(HTTPStatus.OK, {"ok": True})

    def _handle_get_pgn(self) -> None:
        with self._app.lock:
            if not self._app.game.is_finished():
                self._send_json(HTTPStatus.CONFLICT, {"error": "Партия ещё не окончена"})
                return
            text = _build_pgn(self._app)
        body = text.encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("content-type", "text/plain; charset=utf-8")
        self.send_header("content-disposition", 'attachment; filename="game.pgn"')
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _handle_post_new_game(self) -> None:
        with self._app.lock:
            self._app.game = Game()
            self._app.selected_square = None
            self._app.last_eval_cp = None
            self._app.last_eval_depth = None
            self._app.last_eval_nodes = None
        _auto_play_engines(self._app, max_plies=1)
        with self._app.lock:
            self._send_json(HTTPStatus.OK, _state_payload(self._app))

    def _handle_post_set_player(self) -> None:
        try:
            data = self._read_json()
        except ValueError as e:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": str(e)})
            return

        color = data.get("color")
        kind = data.get("kind")
        if color not in ("white", "black"):
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": "Ожидается color = 'white' или 'black'"})
            return
        if kind not in ("human", "random", "material", "positional"):
            self._send_json(
                HTTPStatus.BAD_REQUEST,
                {"error": "Ожидается kind = 'human' | 'random' | 'material' | 'positional'"},
            )
            return

        with self._app.lock:
            if color == "white":
                self._app.white_kind = kind
                if kind == "random":
                    self._app.white_engine = EnginePlayer(RandomEngine())
                elif kind == "material":
                    self._app.white_engine = EnginePlayer(MaterialEngine(MaterialEngineConfig(max_depth=8)))
                elif kind == "positional":
                    self._app.white_engine = EnginePlayer(positional_engine())
            else:
                self._app.black_kind = kind
                if kind == "random":
                    self._app.black_engine = EnginePlayer(RandomEngine())
                elif kind == "material":
                    self._app.black_engine = EnginePlayer(MaterialEngine(MaterialEngineConfig(max_depth=8)))
                elif kind == "positional":
                    self._app.black_engine = EnginePlayer(positional_engine())
            self._app.game = Game()
            self._app.selected_square = None
            self._app.last_eval_cp = None
            self._app.last_eval_depth = None
            self._app.last_eval_nodes = None
        _auto_play_engines(self._app, max_plies=1)
        with self._app.lock:
            self._send_json(HTTPStatus.OK, _state_payload(self._app))

    # старые эндпоинты больше не используются во фронтенде,
    # но оставим заглушки для совместимости
    def _handle_post_set_side(self) -> None:
        self._send_json(HTTPStatus.BAD_REQUEST, {"error": "Эндпоинт устарел. Используйте /api/set-player"})

    def _handle_post_set_engine(self) -> None:
        self._send_json(HTTPStatus.BAD_REQUEST, {"error": "Эндпоинт устарел. Используйте /api/set-player"})
    def _handle_post_set_depth(self) -> None:
        try:
            data = self._read_json()
        except ValueError as e:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": str(e)})
            return

        depth = data.get("depth")
        if not isinstance(depth, int) or depth <= 0 or depth > 8:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": "Ожидается целое depth от 1 до 8"})
            return

        with self._app.lock:
            self._app.search_depth = depth
            self._app.search_nodes = None
            self._app.game = Game()
            self._app.selected_square = None
            self._app.last_eval_cp = None
            self._app.last_eval_depth = None
            self._app.last_eval_nodes = None
        _auto_play_engines(self._app, max_plies=1)
        with self._app.lock:
            self._send_json(HTTPStatus.OK, _state_payload(self._app))

    def _handle_post_set_nodes(self) -> None:
        try:
            data = self._read_json()
        except ValueError as e:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": str(e)})
            return

        nodes = data.get("nodes")
        if not isinstance(nodes, int) or nodes <= 0 or nodes > 5_000_000:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": "Ожидается целое nodes от 1 до 5000000"})
            return

        with self._app.lock:
            self._app.search_nodes = nodes
            self._app.game = Game()
            self._app.selected_square = None
            self._app.last_eval_cp = None
            self._app.last_eval_depth = None
            self._app.last_eval_nodes = None
        _auto_play_engines(self._app, max_plies=1)
        with self._app.lock:
            self._send_json(HTTPStatus.OK, _state_payload(self._app))


    def _handle_post_click(self) -> None:
        try:
            data = self._read_json()
        except ValueError as e:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": str(e)})
            return

        square_name = data.get("square")
        promotion_code = data.get("promotion")
        if not isinstance(square_name, str):
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": "Некорректный запрос"})
            return

        try:
            square = chess.parse_square(square_name)
        except ValueError:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": "Некорректная клетка"})
            return

        with self._app.lock:
            app = self._app
            if app.game.is_finished():
                self._send_json(HTTPStatus.OK, _state_payload(app))
                return

            turn_color = app.game.turn
            if _side_kind(app, turn_color) != "human":
                self._send_json(HTTPStatus.OK, _state_payload(app))
                return

            piece_at_clicked = app.game.board.piece_at(square)

            if app.selected_square is None:
                if piece_at_clicked is None or piece_at_clicked.color != turn_color:
                    self._send_json(HTTPStatus.OK, _state_payload(app))
                    return
                app.selected_square = square
                self._send_json(HTTPStatus.OK, _state_payload(app))
                return

            if square == app.selected_square:
                app.selected_square = None
                self._send_json(HTTPStatus.OK, _state_payload(app))
                return

            if piece_at_clicked is not None and piece_at_clicked.color == turn_color:
                app.selected_square = square
                self._send_json(HTTPStatus.OK, _state_payload(app))
                return

            from_sq = app.selected_square
            to_sq = square

            pawn_moves: list[chess.Move] = []
            piece_from = app.game.board.piece_at(from_sq)
            if piece_from is not None and piece_from.piece_type == chess.PAWN:
                rank_to = chess.square_rank(to_sq)
                if rank_to in (0, 7):
                    for mv in app.game.legal_moves():
                        if mv.from_square == from_sq and mv.to_square == to_sq and mv.promotion is not None:
                            pawn_moves.append(mv)

            if pawn_moves and promotion_code is None:
                choices: list[str] = []
                for mv in pawn_moves:
                    if mv.promotion == chess.QUEEN:
                        choices.append("q")
                    elif mv.promotion == chess.ROOK:
                        choices.append("r")
                    elif mv.promotion == chess.BISHOP:
                        choices.append("b")
                    elif mv.promotion == chess.KNIGHT:
                        choices.append("n")

                payload = _state_payload(app)
                payload.update(
                    {
                        "promotion_required": True,
                        "promotion_from": chess.square_name(from_sq),
                        "promotion_to": chess.square_name(to_sq),
                        "promotion_choices": sorted(set(choices)) or ["q"],
                    }
                )
                self._send_json(HTTPStatus.OK, payload)
                return

            if pawn_moves and isinstance(promotion_code, str):
                promo_map = {"q": chess.QUEEN, "r": chess.ROOK, "b": chess.BISHOP, "n": chess.KNIGHT}
                promo_type = promo_map.get(promotion_code.lower())
                if promo_type is None:
                    self._send_json(HTTPStatus.BAD_REQUEST, {"error": "Некорректная фигура для превращения"})
                    return
                move = chess.Move(from_sq, to_sq, promotion=promo_type)
            else:
                move = chess.Move(from_sq, to_sq)

            if move not in app.game.legal_moves():
                app.selected_square = None
                self._send_json(HTTPStatus.OK, _state_payload(app))
                return

            app.game.make_move(move)
            app.selected_square = None
            self._send_json(HTTPStatus.OK, _state_payload(app))

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        routes = {
            "/": self._handle_get_index,
            "/api/state": self._handle_get_state,
            "/api/ping": self._handle_get_ping,
            "/api/pgn": self._handle_get_pgn,
        }
        handler = routes.get(path)
        if handler is not None:
            handler()
            return

        if path.startswith("/static/"):
            rel = path[len("/static/") :]
            if self._serve_static_file(rel):
                return
            self._send_text(HTTPStatus.NOT_FOUND, "Not found")
            return

        self._send_text(HTTPStatus.NOT_FOUND, "Not found")

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        routes = {
            "/api/new-game": self._handle_post_new_game,
            "/api/click": self._handle_post_click,
            "/api/set-player": self._handle_post_set_player,
            "/api/set-side": self._handle_post_set_side,
            "/api/set-engine": self._handle_post_set_engine,
            "/api/set-depth": self._handle_post_set_depth,
            "/api/set-nodes": self._handle_post_set_nodes,
        }
        handler = routes.get(path)
        if handler is not None:
            handler()
            return

        self._send_json(HTTPStatus.NOT_FOUND, {"error": "Not found"})


class ChessServer(ThreadingHTTPServer):
    def __init__(self, server_address: tuple[str, int], app_state: AppState) -> None:
        super().__init__(server_address, Handler)
        self.app_state = app_state


def main(host: str = "127.0.0.1", port: int = 8000, open_browser: bool = True) -> None:
    default_engine_white = EnginePlayer(MaterialEngine(MaterialEngineConfig(max_depth=8)))
    default_engine_black = EnginePlayer(MaterialEngine(MaterialEngineConfig(max_depth=8)))
    app_state = AppState(
        game=Game(),
        white_kind="human",
        black_kind="material",
        white_engine=default_engine_white,
        black_engine=default_engine_black,
        selected_square=None,
        lock=threading.Lock(),
        last_seen_ts=time.time(),
        shutdown_after_s=300,
        last_eval_cp=None,
        last_eval_depth=None,
        last_eval_nodes=None,
        search_depth=3,
        search_nodes=None,
    )

    server = ChessServer((host, port), app_state)
    url = f"http://{host}:{port}/"
    if open_browser:
        webbrowser.open(url)

    def monitor_idle() -> None:
        while True:
            time.sleep(1.0)
            with app_state.lock:
                idle_for = time.time() - app_state.last_seen_ts
                timeout = app_state.shutdown_after_s
            if idle_for >= timeout:
                server.shutdown()
                return

    threading.Thread(target=monitor_idle, daemon=True).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return


if __name__ == "__main__":
    main()

