#!/usr/bin/env python3
"""
This is a script to build the necessary database from a MPD music library.

Run `python3 server.py --help` for more infos on how to use.
"""
import argparse
import dateutil.parser
import os
import sqlite3
import subprocess

from mpd import MPDClient

if "XDG_DATA_HOME" in os.environ:
    _BLISSIFY_DATA_HOME = os.path.expandvars("$XDG_DATA_HOME/blissify")
else:
    _BLISSIFY_DATA_HOME = os.path.expanduser("~/.local/share/blissify")


def init_connection():
    """
    Returns an MPDClient connection.
    """
    # Get MPD connection settings
    try:
        mpd_host = os.environ["MPD_HOST"]
        mpd_password, mpd_host = mpd_host.split("@")
    except KeyError:
        mpd_host = "localhost"
        mpd_password = None
    try:
        mpd_port = os.environ["MPD_PORT"]
    except KeyError:
        mpd_port = 6600

    # Connect to MPD²
    client = MPDClient()
    client.connect(mpd_host, mpd_port)
    if mpd_password is not None:
        client.password(mpd_password)
    return client


def close_connection(client):
    """
    Closes an MPDClient connection.
    """
    client.close()
    client.disconnect()


def full_rescan(mpd_root):
    """
    Perform a full rescan of the MPD library.
    """
    client = init_connection()
    # Get all songs from MPD and Blissify them
    all_songs = [x["file"] for x in client.listall() if "file" in x]
    subprocess.check_call(["blissify", mpd_root] + all_songs)
    # Update the latest mtime stored
    with open(os.path.join(_BLISSIFY_DATA_HOME, "latest_mtime.txt"), "r") as fh:
        latest_mtime = int(fh.read())
    for song in all_songs:
        last_modified = client.find("file", song)["last_modified"]
        last_modified = int(dateutil.parser.parse(last_modified).timestamp())
        if last_modified > latest_mtime:
            latest_mtime = last_modified
    with open(os.path.join(_BLISSIFY_DATA_HOME, "latest_mtime.txt"), "w") as fh:
        fh.write(latest_mtime)
    close_connection(client)


def rescan_errored(mpd_root):
    """
    Rescan only errored files.
    """
    # Connect to db
    db_path = os.path.join(_BLISSIFY_DATA_HOME, "db.sqlite3")
    logging.debug("Using DB path: %s." % (db_path,))
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute('pragma foreign_keys=ON')
    cur = conn.cursor()
    # Get errored files
    cur.execute("SELECT filename FROM errors")
    errors = cur.fetchall()
    # Rerun blissify on them
    if errors is not None:
        subprocess.check_call(["blissify", mpd_root] + errors)


def update_db(mpd_root):
    """
    Update the blissify db taking newly added songs in MPD library.
    """
    client = init_connection()
    with open(os.path.join(_BLISSIFY_DATA_HOME, "latest_mtime.txt"), "r") as fh:
        latest_mtime = int(fh.read())
    songs = [x["file"] for x in client.find("modified-since", latest_mtime)]
    subprocess.check_call(["blissify", mpd_root] + songs)
    # Update the latest mtime stored
    with open(os.path.join(_BLISSIFY_DATA_HOME, "latest_mtime.txt"), "r") as fh:
        latest_mtime = int(fh.read())
    for song in songs:
        last_modified = client.find("file", song)["last_modified"]
        last_modified = int(dateutil.parser.parse(last_modified).timestamp())
        if last_modified > latest_mtime:
            latest_mtime = last_modified
    with open(os.path.join(_BLISSIFY_DATA_HOME, "latest_mtime.txt"), "w") as fh:
        fh.write(latest_mtime)
    close_connection(client)


def listen(mpd_root):
    """
    Listen for additions in MPD library using MPD IDLE and handle them
    immediately.
    """
    client = init_connection()
    while True:
        try:
            client.idle("database")
        except KeyboardInterrupt:
            break
        update_db(mpd_root)
    close_connection(client)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("mpd_root", help="Root folder of your MPD library.")

    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--full-rescan", help="Scan the whole library.",
                       action="store_true", default=False)
    group.add_argument("--rescan-errored", help="Rescan errored files.",
                       action="store_true", default=False)
    group.add_argument("--update",
                       help="Update the database with new files in the library",
                       action="store_true", default=False)
    group.add_argument("--listen",
                       help="Listen for MPD IDLE signals to do live scanning.",
                       action="store_true", default=False)

    args = parser.parse_args()

    if args.full_rescan:
        full_rescan(args.mpd_root)
    elif args.rescan_errored:
        rescan_errored(args.mpd_root)
    elif args.update:
        update_db(args.mpd_root)
    elif args.listen:
        listen(args.mpd_root)
    else:
        sys.exit()
