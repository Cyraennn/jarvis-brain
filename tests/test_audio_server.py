"""NetworkAudioServer: auth, tek-istemci kurali, mikrofon/hoparlor cerceve round-trip."""
import asyncio
import contextlib
import socket

import pytest
from websockets.asyncio.client import connect
from websockets.exceptions import InvalidStatus

from net.audio_server import TAG_MIC, TAG_SPEAKER, NetworkAudioServer


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_no_token_forces_loopback_bind():
    srv = NetworkAudioServer(port=1, bind="0.0.0.0", token="")
    assert srv.bind == "127.0.0.1"


def test_token_allows_configured_bind():
    srv = NetworkAudioServer(port=1, bind="0.0.0.0", token="s3cret")
    assert srv.bind == "0.0.0.0"


async def _with_running_server(srv: NetworkAudioServer, body):
    task = asyncio.create_task(srv.run())
    try:
        await asyncio.sleep(0.2)
        await body()
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


def test_rejects_connection_without_token():
    async def _run():
        port = _free_port()
        srv = NetworkAudioServer(port=port, bind="127.0.0.1", token="s3cret")

        async def _body():
            with pytest.raises(InvalidStatus) as exc:
                async with connect(f"ws://127.0.0.1:{port}/"):
                    pass
            assert exc.value.response.status_code == 401

        await _with_running_server(srv, _body)

    asyncio.run(_run())


def test_mic_and_speaker_round_trip():
    async def _run():
        port = _free_port()
        srv = NetworkAudioServer(port=port, bind="127.0.0.1", token="s3cret")

        async def _body():
            async with connect(f"ws://127.0.0.1:{port}/?key=s3cret") as client:
                await asyncio.sleep(0.1)
                assert srv.client_connected is True

                # istemci -> sunucu (mikrofon)
                await client.send(bytes([TAG_MIC]) + b"\x11\x22\x33\x44")
                mic_chunk = await asyncio.wait_for(srv.read_mic_chunk(), timeout=2.0)
                assert mic_chunk == b"\x11\x22\x33\x44"

                # sunucu -> istemci (hoparlor)
                await srv.send_speaker_chunk(b"\x55\x66")
                frame = await asyncio.wait_for(client.recv(), timeout=2.0)
                assert frame[0] == TAG_SPEAKER
                assert frame[1:] == b"\x55\x66"
            await asyncio.sleep(0.1)
            assert srv.client_connected is False

        await _with_running_server(srv, _body)

    asyncio.run(_run())


def test_second_client_rejected_while_first_connected():
    async def _run():
        port = _free_port()
        srv = NetworkAudioServer(port=port, bind="127.0.0.1", token="s3cret")

        async def _body():
            async with connect(f"ws://127.0.0.1:{port}/?key=s3cret"):
                await asyncio.sleep(0.1)
                with pytest.raises(InvalidStatus) as exc:
                    async with connect(f"ws://127.0.0.1:{port}/?key=s3cret"):
                        pass
                assert exc.value.response.status_code == 409

        await _with_running_server(srv, _body)

    asyncio.run(_run())
