# Small script for clearing disc space when there is not much room left
from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path

import requests

# ruff: noqa: T201

type SID = str

_HEARTBEAT_FILE: Path = Path().cwd() / "janitor_heartbeat.txt"
_QBIT_SID_FILE: Path = Path().cwd() / "janitor_qbit_sid.txt"

QBIT_IP = os.getenv("QBIT_IP")
QBIT_PORT = os.getenv("QBIT_PORT")
QBIT_LOGIN = os.getenv("QBIT_LOGIN")
QBIT_PASSWORD = os.getenv("QBIT_PASSWORD")
QBIT_CLEANUP_MIN_LEFT_SPACE_GIB = float(os.getenv("QBIT_CLEANUP_MIN_LEFT_SPACE_GIB"))


def _write_heartbeat() -> None:
    """Writes to a file that is used as health check in docker"""
    print("Writing BEAT to file")
    with _HEARTBEAT_FILE.open("w") as f:
        f.write("BEAT")


def _write_qbit_sid(sid: SID) -> None:
    """Writes qBittorrent Session ID to file"""
    print("Writing qBittorrent Session ID to file")
    with _QBIT_SID_FILE.open("w") as f:
        f.write(sid)


def _read_qbit_sid() -> SID | None:
    """Reads qBittorrent Session ID from file"""
    print("Reading qBittorrent Session ID from file")
    if not _QBIT_SID_FILE.exists():
        return None
    sid = None
    with _QBIT_SID_FILE.open() as f:
        sid = f.read().strip()

    return sid if len(sid) > 0 else None


def qbit_login() -> SID:
    print("qBittorrent /api/v2/auth/login")
    data = requests.post(
        f"http://{QBIT_IP}:{QBIT_PORT}/api/v2/auth/login",
        data={
            "username": QBIT_LOGIN,
            "password": QBIT_PASSWORD,
        },
        timeout=60,
    )
    if data.status_code != requests.codes.ok:
        msg = "Failed to login to qBittorrent"
        raise RuntimeError(msg)

    sid: SID = ""
    for elem in data.headers["set-cookie"].split(";"):
        if "SID=" in elem:
            sid = elem[4:].strip()
    if not sid:
        msg = "Failed to retrieve SID from qBittorrent during login."
        raise RuntimeError(msg)

    _write_qbit_sid(sid)
    return sid


def qbit_test_connection(sid: SID) -> bool:
    data = requests.get(
        f"http://{QBIT_IP}:{QBIT_PORT}/api/v2/app/version",
        cookies={"SID": sid},
        timeout=60,
    )
    print(f"Testing qBittorrent connection {data.status_code}, {data.text}")
    if data.status_code != requests.codes.ok:
        return False
    return True


def qbit_get_torrents_list(sid: SID):
    response = requests.post(
        f"http://{QBIT_IP}:{QBIT_PORT}/api/v2/torrents/info",
        data={
            "filter": "completed",
            "sort": "added_on",
        },
        cookies={"SID": sid},
        timeout=60,
    )
    if response.status_code != requests.codes.ok:
        msg = "Failed to get list of torrents"
        raise requests.exceptions.ConnectionError(msg)

    return response.json()


def qbit_get_free_disc_space(sid: SID) -> int:
    response = requests.get(
        f"http://{QBIT_IP}:{QBIT_PORT}/api/v2/sync/maindata",
        cookies={"SID": sid},
        timeout=60,
    )
    return response.json()["server_state"]["free_space_on_disk"]


def qbit_delete_torrents(sid: SID, torrents: list[str]):
    response = requests.post(
        f"http://{QBIT_IP}:{QBIT_PORT}/api/v2/torrents/delete",
        data={"deleteFiles": "true", "hashes": "|".join(torrents)},
        cookies={"SID": sid},
        timeout=60,
    )
    if response.status_code != requests.codes.ok:
        msg = "Failed to delete list of torrents"
        raise requests.exceptions.ConnectionError(msg)


def qbit_delete_if_no_room_left(sid: SID, torrents: list[dict]):
    free_space: int = qbit_get_free_disc_space(sid)
    print(f"Space left: {free_space} ~= {free_space / 1024 ** 3:0.2f} GiB")

    if free_space > QBIT_CLEANUP_MIN_LEFT_SPACE_GIB * (1024**3):
        print("There is still enough room... skip")
        return

    to_delete: list[str] = []
    new_space: int = 0

    elem = torrents[0]
    print(
        f"DELETE {datetime.fromtimestamp(elem['added_on'], UTC).strftime('%Y-%m-%d %H:%M:%S')} hash={elem['hash']} ratio={elem['ratio']:0.2f} path={elem['content_path']}",
    )
    to_delete.append(elem["hash"])
    new_space += elem["size"]

    print(f"{new_space / 1024 ** 3:0.2f} GiB will be reclaimed")
    qbit_delete_torrents(sid, to_delete)


def clean_qbittorrent() -> None:
    sid: SID = _read_qbit_sid()
    if sid is None or not qbit_test_connection(sid):
        sid = qbit_login()

    torrents = qbit_get_torrents_list(sid)
    print("Listing torrents...")
    for elem in torrents:
        print(
            f"- {datetime.fromtimestamp(elem['added_on'], UTC).strftime('%Y-%m-%d %H:%M:%S')} hash={elem['hash']} ratio={elem['ratio']:0.2f} path={elem['content_path']}",
        )

    qbit_delete_if_no_room_left(sid, torrents)


def main():
    clean_qbittorrent()
    _write_heartbeat()


if __name__ == "__main__":
    main()
