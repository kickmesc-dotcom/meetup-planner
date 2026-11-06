"""Сжатие ответов API: включается по размеру и не трогает фото.

Зачем тест. `content-encoding` — та вещь, которую легко «включить» и не
заметить, что не работает: gzip решает по размеру тела и по заголовку
`Accept-Encoding`, а фото должно остаться несжатым. Поэтому проверяем оба
направления: большой JSON сжимается, маленький — нет, а байтовая выдача фото
помечена `identity` и через gzip не идёт.

Приложение собирается вокруг `add_compression` из `app.main` — той же функции,
которую вызывает `create_app`, поэтому тест не может разойтись с продом.
"""

from __future__ import annotations

import json

from fastapi import FastAPI, Response
from fastapi.testclient import TestClient

from app.api.routes_media import media_headers
from app.main import GZIP_MINIMUM_SIZE, add_compression

BIG = {"items": [f"строка-{index}-" + "x" * 40 for index in range(40)]}


def _client() -> TestClient:
    app = FastAPI()
    add_compression(app)

    @app.get("/api/big")
    async def big() -> dict[str, object]:
        return BIG

    @app.get("/api/small")
    async def small() -> dict[str, bool]:
        return {"ok": True}

    @app.get("/api/photo")
    async def photo() -> Response:
        # 4 КБ «фото»: размер выше порога, но тип уже сжатый.
        return Response(
            content=b"\xff\xd8" + b"0" * 4096,
            media_type="image/jpeg",
            headers=media_headers(),
        )

    return TestClient(app)


def test_big_json_is_gzipped_and_unzips_to_the_same_data() -> None:
    with _client() as client:
        response = client.get("/api/big", headers={"Accept-Encoding": "gzip"})

    assert response.status_code == 200
    assert response.headers.get("content-encoding") == "gzip"
    # httpx распаковывает gzip сам, поэтому тело читаем как обычный JSON, а
    # реальный размер сжатия берём из `content-length`: Starlette ставит его
    # для уже сжатого тела.
    assert response.json() == BIG
    raw = len(json.dumps(BIG, ensure_ascii=False).encode("utf-8"))
    # Сжатый `content-length` меньше сырого — значит тело реально пожато, а не
    # только помечено заголовком.
    assert int(response.headers["content-length"]) < raw


def test_small_json_is_left_alone() -> None:
    with _client() as client:
        response = client.get("/api/small", headers={"Accept-Encoding": "gzip"})

    assert response.status_code == 200
    assert response.headers.get("content-encoding") is None
    assert response.json() == {"ok": True}


def test_client_without_gzip_support_gets_plain_body() -> None:
    with _client() as client:
        response = client.get("/api/big", headers={"Accept-Encoding": "identity"})

    assert response.headers.get("content-encoding") is None
    assert response.json() == BIG


def test_photo_bytes_are_not_gzipped() -> None:
    with _client() as client:
        response = client.get("/api/photo", headers={"Accept-Encoding": "gzip"})

    assert response.headers["content-encoding"] == "identity"
    assert response.headers["content-type"].startswith("image/jpeg")
    assert response.content.startswith(b"\xff\xd8")
    assert len(response.content) > GZIP_MINIMUM_SIZE
