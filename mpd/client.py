#!/usr/bin/env python3
"""
This is a client for MPD to generate a random playlist starting from the last
song of the current playlist and iterating using values computed using Bliss.

MPD connection settings are taken from environment variables, following MPD_HOST
and MPD_PORT scheme described in `mpc` man.

You can pass an integer argument to the script to change the length of the
generated playlist (default is to add 20 songs).
"""
import argparse
import logging
import math
import os
import random
import sqlite3
import socket
import sys
import enum
import mpd
import random

class PersistentMPDClient(mpd.MPDClient):
    """
    From
    https://github.com/schamp/PersistentMPDClient/blob/master/PersistentMPDClient.py
    """
    def __init__(self, socket=None, host=None, port=None):
        super().__init__()
        self.socket = socket
        self.host = host
        self.port = port

        self.do_connect()
        # get list of available commands from client
        self.command_list = self.commands()

        # commands not to intercept
        self.command_blacklist = ['ping']

        # wrap all valid MPDClient functions
        # in a ping-connection-retry wrapper
        for cmd in self.command_list:
            if cmd not in self.command_blacklist:
                if hasattr(super(PersistentMPDClient, self), cmd):
                    super_fun = super(PersistentMPDClient, self).__getattribute__(cmd)
                    new_fun = self.try_cmd(super_fun)
                    setattr(self, cmd, new_fun)

    # create a wrapper for a function (such as an MPDClient
    # member function) that will verify a connection (and
    # reconnect if necessary) before executing that function.
    # functions wrapped in this way should always succeed
    # (if the server is up)
    # we ping first because we don't want to retry the same
    # function if there's a failure, we want to use the noop
    # to check connectivity
    def try_cmd(self, cmd_fun):
        def fun(*pargs, **kwargs):
            try:
                self.ping()
            except (mpd.ConnectionError, OSError):
                self.do_connect()
            return cmd_fun(*pargs, **kwargs)
        return fun

    # needs a name that does not collide with parent connect() function
    def do_connect(self):
        try:
            try:
                self.disconnect()
            # if it's a TCP connection, we'll get a socket error
            # if we try to disconnect when the connection is lost
            except mpd.ConnectionError:
                pass
            # if it's a socket connection, we'll get a BrokenPipeError
            # if we try to disconnect when the connection is lost
            # but we have to retry the disconnect, because we'll get
            # an "Already connected" error if we don't.
            # the second one should succeed.
            except BrokenPipeError:
                try:
                    self.disconnect()
                except:
                    print("Second disconnect failed, yikes.")
            if self.socket:
                self.connect(self.socket, None)
            else:
                self.connect(self.host, self.port)
        except socket.error:
            print("Connection refused.")


logging.basicConfig(level=logging.INFO)

_QUEUE_LENGTH = 20

if "XDG_DATA_HOME" in os.environ:
    _BLISSIFY_DATA_HOME = os.path.expandvars("$XDG_DATA_HOME/blissify")
else:
    _BLISSIFY_DATA_HOME = os.path.expanduser("~/.local/share/blissify")


def distance(x, y):
    """
    Compute the distance between two songs.

    Params:
        - x: First song dict
        - y: Second song dict
    Returns: The cartesian distance between the two songs.
    """
    return math.sqrt(
        (x["tempo"] - y["tempo"])**2 +
        (x["amplitude"] - y["amplitude"])**2 +
        (x["frequency"] - y["frequency"])**2 +
        (x["attack"] - y["attack"])**2
    )


def mean_song(X):
    """
    Compute a "mean" song for a given iterable of song dicts.

    Params:
        - X: An iterable of song dicts.
    Returns: A "mean" song, whose features are the mean features of the songs
    in the iterable.
    """

    result = {'tempo': 0, 'amplitude': 0, 'frequency': 0, 'attack': 0}

    count = len(X)

    for song in X:
        result["tempo"] += song["tempo"]
        result["amplitude"] += song["amplitude"]
        result["frequency"] += song["frequency"]
        result["attack"] += song["attack"]

    result["tempo"] /= count
    result["amplitude"] /= count
    result["frequency"] /= count
    result["attack"] /= count
    return result


def distance_sets(X, Y):
    """
    Compute the distance between two iterables of song dicts, defined as the
    distance between the two mean songs of the iterables.

    Params:
        - X: First iterable of song dicts.
        - Y: First iterable of song dicts.
    Returns: The distance between the two iterables.
    """
    return distance(mean_song(X), mean_song(Y))


def _init():
    # Get MPD connection settings
    try:
        mpd_host = os.environ["MPD_HOST"]
        try:
            mpd_password, mpd_host = mpd_host.split("@")
        except ValueError:
            mpd_password = None
    except KeyError:
        mpd_host = "localhost"
        mpd_password = None
    try:
        mpd_port = os.environ["MPD_PORT"]
    except KeyError:
        mpd_port = 6600

    # Connect to MPD
    client = PersistentMPDClient(host=mpd_host, port=mpd_port)
    if mpd_password is not None:
        client.password(mpd_password)
    # Connect to db
    db_path = os.path.join(_BLISSIFY_DATA_HOME, "db.sqlite3")
    logging.debug("Using DB path: %s." % (db_path,))
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute('pragma foreign_keys=ON')
    cur = conn.cursor()

    # Ensure random is not enabled
    status = client.status()
    if int(status["random"]) != 0:
        logging.warning("Random mode is enabled. Are you sure you want it?")

    # Take the last song from current playlist and iterate from it
    playlist = client.playlist()
    if len(playlist) > 0:
        current_song = playlist[-1].replace("file: ", "").rstrip()
    # If current playlist is empty
    else:
        # Add a random song to start with TODO add a random album
        all_songs = [x["file"] for x in client.listall() if "file" in x]
        current_song = random.choice(all_songs)
        client.add(current_song)

    logging.info("Currently played song is %s." % (current_song,))

    # Get current song coordinates
    cur.execute("SELECT id, tempo, amplitude, frequency, attack, filename, album FROM songs WHERE filename=?", (current_song,))
    current_song_coords = cur.fetchone()
    if current_song_coords is None:
        logging.error("Current song %s is not in db. You should update the db." %
                      (current_song,))
        client.close()
        client.disconnect()
        sys.exit(1)

    return client, conn, cur, current_song_coords


def main_album(queue_length, option_best=True):
    client, conn, cur, current_song_coords = _init()

    # Get 'queue_length' random albums
    for i in range(queue_length):
        # No cache management
        # Get all songs from the current album
        distance_array = []

        # Get album name and all of this album's songs coordinates
        album_name = current_song_coords["album"]
        cur.execute("SELECT id, tempo, amplitude, frequency, attack, filename, album FROM songs WHERE album=?", (album_name,))
        target_album_set = cur.fetchall()

        # Get all albums
        cur.execute("SELECT DISTINCT album FROM songs")
        albums = cur.fetchall();

        # Compute the distance between current album and all other albums
        for tmp_album in albums:
            # Get all songs in the album
            cur.execute("SELECT id, tempo, amplitude, frequency, attack, filename, album FROM songs WHERE album=?", (tmp_album["album"],))
            tmp_songs = cur.fetchall()
            # Don't compute distance for the current album and albums already in the playlist
            if(tmp_album["album"] == target_album_set[0]["album"] or
               ("file: %s" % (tmp_songs[0]["filename"],)) in client.playlist()):
                # Skip current song and already processed songs
                logging.debug("Skipping %s." % (tmp_album["album"]))
                continue
           
            tmp_distance = distance_sets(tmp_songs, target_album_set)
            distance_array.append({'Distance': tmp_distance, 'Album': tmp_songs})
            logging.debug("Distance between %s and %s is %f." %
                (target_album_set[0]["album"],
                tmp_album["album"], tmp_distance))

        # Ascending sort by distance (the lower the closer)
        distance_array.sort(key=lambda x: x["Distance"])

        # Chose between best album and one of the top 10 at random
        indice = 0 if option_best else random.randrange(10)
        
        logging.info("Closest album found is \"%s\". Distance is %f." %
            (distance_array[indice]["Album"][0]["album"], distance_array[indice]["Distance"]))

        for song in distance_array[indice]["Album"]:
            client.add(song["filename"])

    conn.close()
    client.close()
    client.disconnect()


def main_single(queue_length, option_best=True):
    client, conn, cur, current_song_coords = _init()

    # Get 'queue_length' random songs
    for i in range(queue_length):
        distance_array = []

        # Get all other songs coordinates and iterate on them
        cur.execute("SELECT id, tempo, amplitude, frequency, attack, filename FROM songs")
        for tmp_song_data in cur.fetchall():
            # Skip current song and already processed songs
            if(tmp_song_data["filename"] == current_song_coords["filename"] or
               ("file: %s" % (tmp_song_data["filename"],)) in client.playlist()):
                logging.debug("Skipping %s." % (tmp_song_data["filename"]))
                continue
            # Compute distance between current song and songs in the loop
            tmp_distance = distance(tmp_song_data, current_song_coords)
            distance_array.append({'Distance': tmp_distance, 'Song': tmp_song_data})
            logging.debug("Distance between %s and %s is %f." %
                (current_song_coords["filename"],
                tmp_song_data["filename"], tmp_distance))

        # Ascending sort by distance (the lower the closer)
        distance_array.sort(key=lambda x: x['Distance'])

        # Chose between best album and one of the top 10 at random
        indice = 0 if option_best else random.randrange(10)

        current_song_coords = distance_array[indice]['Song']

        client.add(current_song_coords["filename"])
        logging.info("Found a close song: %s. Distance is %f." %
            (current_song_coords["filename"], distance_array[0]['Distance']))

    conn.close()
    client.close()
    client.disconnect()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--queue-length", help="The number of items to add to the MPD playlist.", type=int)
    parser.add_argument("--best-playlist", help="Makes the best possible playlist, always the same for a fixed song/album",
        action='store_true', default=True)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--song-based", help="Make a playlist based on single songs.",
        action="store_true", default=False)
    group.add_argument("--album-based", help="Make a playlist based on whole albums.",
        action="store_true", default=False)

    args = parser.parse_args()
    if args.queue_length:
        queue_length = args.queue_length
    else:
        queue_length = _QUEUE_LENGTH

    if args.song_based:
        main_single(queue_length, args.best_playlist)
    elif args.album_based:
        main_album(queue_length, args.best_playlist)

