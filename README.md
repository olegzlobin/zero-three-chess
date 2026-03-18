# Zero-Three Chess

Экспериментальная платформа для разработки и тестирования шахматных движков на Python поверх `python-chess`.

Состоит из трёх основных слоёв:

- **core** – логика партии (`Game`, `Player`, `GameSession`).
- **engines** – интерфейс и реализации движков (пока только `RandomEngine`).
- **app** – приложения: веб-клиент и CLI.

## Установка (локально)

```bash
git clone <repo-url> zero-three-chess
cd zero-three-chess
python -m venv .venv
. .venv/bin/activate
python -m pip install -e .
```

Требуется Python 3.10+.

## Веб-клиент

Запуск локального HTTP-сервера и открытие браузера:

```bash
cd zero-three-chess
. .venv/bin/activate
python -m zero_three_chess.app.web_app
```

По умолчанию сервер слушает `http://127.0.0.1:8000/` и автоматически открывает вкладку в браузере.

Возможности веб-клиента:

- Игра человек vs `RandomEngine`.
- Выбор стороны (белыми/чёрными) с автоматическим переворотом доски.
- Подсветка доступных ходов и последнего хода.
- Превращение пешки с выбором фигуры.

## Архитектура движка

Интерфейс движка описан в `zero_three_chess/engines/base.py`:

- `SearchLimit` – глубина, ограничение по времени и по числу узлов.
- `EngineResult` – лучший ход + метаданные (оценка, глубина, PV и т.д.).
- `Engine` (Protocol) с методом:

```python
def select(self, board: chess.Board, limit: SearchLimit | None = None) -> EngineResult: ...
```

`EnginePlayer` в `core/player.py` адаптирует любой `Engine` к интерфейсу `Player`, который использует `Game`.

## Дальнейшее развитие

Планируемые шаги:

- Добавить реальные движки (минимакс / альфа-бета и др.).
- Реализовать матч-раннер для массовых партий движок vs движок.
- Расширить веб-интерфейс панелью для наблюдения за несколькими партиями.

