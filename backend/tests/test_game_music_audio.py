"""GHG11(6): прослушивание трека подборки, загруженного боту.

Файла у сервера нет: трек (`kind='audio'`) живёт в Telegram по `file_id`, и
ручка проксирует его клиенту — ровно как голосовые сдачи. Прод-баг был в
другом месте (лента рисовала «▶️» только по `url`, т.е. у ссылок), но именно
этот роут даёт мини-аппу звук, поэтому проверяем проводку: 404 на
несуществующий и ссылочный трек, 502 когда Telegram не отдал файл, 413 на
слишком большой файл и MIME по расширению.
"""
from __future__ import annotations

import io

import pytest
from fastapi import HTTPException

from app.api import routes_game
from app.db.models import MusicTrack


class _FakeSession:
    def __init__(self, track: MusicTrack | None) -> None:
        self._track = track

    # Фейк под `session.get`: ручке нужен только сам трек.
    async def get(self, _model, _pk):
        return self._track


class _FakeTGFile:
    def __init__(self, file_path: str = "music/file_11.mp3", file_size: int = 1024):
        self.file_path = file_path
        self.file_size = file_size


def _install_bot(monkeypatch, *, tg_file=None, data: bytes = b"ID3fake", error=None):
    import app.bot.dispatcher as dispatcher

    class _Bot:
        async def get_file(self, _file_id: str):
            if error is not None:
                raise error
            return tg_file

        async def download_file(self, _path: str):
            return io.BytesIO(data)

    monkeypatch.setattr(dispatcher, "get_bot", lambda: _Bot())


def _audio_track() -> MusicTrack:
    return MusicTrack(
        id=11, user_id=1, kind="audio", file_id="fid", status="published"
    )


@pytest.mark.asyncio
async def test_streams_uploaded_track_by_file_id(monkeypatch):
    _install_bot(monkeypatch, tg_file=_FakeTGFile())
    resp = await routes_game.music_track_audio(11, _FakeSession(_audio_track()), None)
    assert resp.body == b"ID3fake"
    assert resp.media_type == "audio/mpeg"


@pytest.mark.asyncio
async def test_unknown_track_is_404(monkeypatch):
    _install_bot(monkeypatch, tg_file=_FakeTGFile())
    with pytest.raises(HTTPException) as exc:
        await routes_game.music_track_audio(404, _FakeSession(None), None)
    assert exc.value.status_code == 404
    assert exc.value.detail == "track_not_found"


@pytest.mark.asyncio
async def test_link_track_has_no_proxy(monkeypatch):
    """Ссылочный трек играется на своём источнике — проксировать нечего."""
    _install_bot(monkeypatch, tg_file=_FakeTGFile())
    track = MusicTrack(
        id=12, user_id=1, kind="link", url="https://youtu.be/x", status="published"
    )
    with pytest.raises(HTTPException) as exc:
        await routes_game.music_track_audio(12, _FakeSession(track), None)
    assert exc.value.status_code == 404
    assert exc.value.detail == "track_has_no_audio"


@pytest.mark.asyncio
async def test_telegram_failure_is_502(monkeypatch):
    _install_bot(monkeypatch, error=RuntimeError("boom"))
    with pytest.raises(HTTPException) as exc:
        await routes_game.music_track_audio(11, _FakeSession(_audio_track()), None)
    assert exc.value.status_code == 502
    assert exc.value.detail == "audio_unavailable"


@pytest.mark.asyncio
async def test_broken_bot_token_is_502_not_500(monkeypatch):
    """Хост с невалидным BOT_TOKEN (как HF) не должен падать 500."""
    import app.bot.dispatcher as dispatcher

    def _boom():
        raise RuntimeError("TokenValidationError")

    monkeypatch.setattr(dispatcher, "get_bot", _boom)
    with pytest.raises(HTTPException) as exc:
        await routes_game.music_track_audio(11, _FakeSession(_audio_track()), None)
    assert exc.value.status_code == 502
    assert exc.value.detail == "audio_unavailable"


@pytest.mark.asyncio
async def test_too_large_is_413(monkeypatch):
    _install_bot(
        monkeypatch,
        tg_file=_FakeTGFile(file_size=routes_game._MUSIC_AUDIO_MAX_BYTES + 1),
    )
    with pytest.raises(HTTPException) as exc:
        await routes_game.music_track_audio(11, _FakeSession(_audio_track()), None)
    assert exc.value.status_code == 413
    assert exc.value.detail == "audio_too_large"


@pytest.mark.parametrize(
    "file_path,expected",
    [
        ("music/a.mp3", "audio/mpeg"),
        ("music/a.MP3", "audio/mpeg"),
        ("music/a.m4a", "audio/mp4"),
        ("music/a.ogg", "audio/ogg"),
        ("music/a.opus", "audio/ogg"),
        ("music/a.flac", "audio/flac"),
        ("music/a.unknown", "audio/mpeg"),
        (None, "audio/mpeg"),
    ],
)
def test_mime_by_extension(file_path, expected):
    assert routes_game._music_media_type(file_path) == expected
