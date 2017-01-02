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

import mpd


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
_DISTANCE_THRESHOLD = 4.0
_SIMILARITY_THRESHOLD = 0.95

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
    count = 0
    result = {'tempo': 0, 'amplitude': 0, 'frequency': 0, 'attack': 0}

    for song in X:
        result["tempo"] += song["tempo"]
        result["amplitude"] += song["amplitude"]
        result["frequency"] += song["frequency"]
        result["attack"] += song["attack"]
        count = count + 1
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


def main_album(queue_length):
    client, conn, cur, current_song_coords = _init()

    for i in range(queue_length):
        # No cache management
        # Get all songs from the current album
        album = current_song_coords["album"]
        cur.execute("SELECT id, tempo, amplitude, frequency, attack, filename, album FROM songs WHERE album=?", (album,))
        target_album_set = cur.fetchall()

        # Get all other songs
        cur.execute("SELECT id, tempo, amplitude, frequency, attack, filename, album FROM songs ORDER BY album")
        tmp_song_data = cur.fetchone()
        shortest_distance = -1

        # Check the best suitable album
        while tmp_song_data:
            current_album_set = list()
            current_album_set.append(tmp_song_data)
            tmp_song_data = cur.fetchone()

            i = 0
            # Get all songs from the current temporary album
            while tmp_song_data:
                if (current_album_set[i]["album"] == tmp_song_data["album"]):
                    current_album_set.append(tmp_song_data)
                else:
                    break
                tmp_song_data = cur.fetchone()
                i = i + 1
            # Skip current album and already processed albums
            if((current_album_set[0]["album"] != target_album_set[0]["album"]) and
               not (("file: %s" % (current_album_set[0]["filename"],)) in client.playlist())):
                tmp_distance = distance_sets(current_album_set, target_album_set)
                if tmp_distance < shortest_distance or shortest_distance == -1:
                    shortest_distance = tmp_distance
                    closest_album = current_album_set

        logging.info("Closest album found is \"%s\". Distance is %f." % (closest_album[0]["album"], shortest_distance))
        for song in closest_album:
            client.add(song["filename"])
        current_song_coords = closest_album[-1]

    conn.close()
    client.close()
    client.disconnect()


def main_single(queue_length):
    client, conn, cur, current_song_coords = _init()

    for i in range(queue_length):
        # Get cached distances from db
        cur.execute(
            "SELECT id, filename, distance, similarity, tempo, amplitude, frequency, attack FROM (SELECT s2.id AS id, s2.filename AS filename, s2.tempo AS tempo, s2.amplitude AS amplitude, s2.frequency AS frequency, s2.attack AS attack, distances.distance AS distance, distances.similarity AS similarity FROM distances INNER JOIN songs AS s1 ON s1.id=distances.song1 INNER JOIN songs AS s2 on s2.id=distances.song2 WHERE s1.filename=? UNION SELECT s1.id as id, s1.filename AS filename, s1.tempo AS tempo, s1.amplitude AS amplitude, s1.frequency AS frequency, s1.attack AS attack, distances.distance as distance, distances.similarity AS similarity FROM distances INNER JOIN songs AS s1 ON s1.id=distances.song1 INNER JOIN songs AS s2 on s2.id=distances.song2 WHERE s2.filename=?) ORDER BY distance ASC",
            (current_song_coords["filename"], current_song_coords["filename"]))
        cached_distances = [row
                            for row in cur.fetchall()
                            if ("file: %s" % (row["filename"],)) not in client.playlist()]
        cached_distances_songs = [i["filename"] for i in cached_distances]
        # Keep track of closest song
        if cached_distances:
            closest_song = (cached_distances[0],
                            cached_distances[0]["distance"],
                            cached_distances[0]["similarity"])
        else:
            closest_song = None

        # Get the songs close enough
        cached_distances_close_enough = [
            row for row in cached_distances
            if row["distance"] < _DISTANCE_THRESHOLD and row["similarity"] > _SIMILARITY_THRESHOLD ]
        if len(cached_distances_close_enough) > 0:
            # If there are some close enough songs in the cache
            random_close_enough = random.choice(cached_distances_close_enough)
            # Push it on the queue
            client.add(random_close_enough["filename"])
            # Continue using latest pushed song as current song
            logging.info("Using cached distance. Found %s. Distance is (%f, %f)." %
                         (random_close_enough["filename"],
                          random_close_enough["distance"],
                          random_close_enough["similarity"]))
            current_song_coords = random_close_enough
            continue

        # Get all other songs coordinates and iterate randomly on them
        cur.execute("SELECT id, tempo, amplitude, frequency, attack, filename FROM songs ORDER BY RANDOM()")
        for tmp_song_data in cur.fetchall():
            if(tmp_song_data["filename"] == current_song_coords["filename"] or
               tmp_song_data["filename"] in cached_distances_songs or
               ("file: %s" % (tmp_song_data["filename"],)) in client.playlist()):
                # Skip current song and already processed songs
                logging.debug("Skipping %s." % (tmp_song_data["filename"]))
                continue
            # Compute distance
            distance = math.sqrt(
                (current_song_coords["tempo"] - tmp_song_data["tempo"])**2 +
                (current_song_coords["amplitude"] - tmp_song_data["amplitude"])**2 +
                (current_song_coords["frequency"] - tmp_song_data["frequency"])**2 +
                (current_song_coords["attack"] - tmp_song_data["attack"])**2
            )
            similarity = (
                (current_song_coords["tempo"] * tmp_song_data["tempo"] +
                 current_song_coords["amplitude"] * tmp_song_data["amplitude"] +
                 current_song_coords["frequency"] * tmp_song_data["frequency"] +
                 current_song_coords["attack"] * tmp_song_data["attack"]) /
                (
                    math.sqrt(
                        current_song_coords["tempo"]**2 +
                        current_song_coords["amplitude"]**2 +
                        current_song_coords["frequency"]**2 +
                        current_song_coords["attack"]**2) *
                    math.sqrt(
                        tmp_song_data["tempo"]**2 +
                        tmp_song_data["amplitude"]**2 +
                        tmp_song_data["frequency"]**2 +
                        tmp_song_data["attack"]**2)
                )
            )
            logging.debug("Distance between %s and %s is (%f, %f)." %
                          (current_song_coords["filename"],
                           tmp_song_data["filename"], distance, similarity))
            # Store distance in db cache
            try:
                logging.debug("Storing distance in database.")
                conn.execute(
                    "INSERT INTO distances(song1, song2, distance, similarity) VALUES(?, ?, ?, ?)",
                    (current_song_coords["id"], tmp_song_data["id"], distance,
                     similarity))
                conn.commit()
            except sqlite3.IntegrityError:
                logging.warning("Unable to insert distance in database.")
                conn.rollback()

            # Update the closest song
            if closest_song is None or distance < closest_song[1]:
                closest_song = (tmp_song_data, distance, similarity)

            # If distance is ok, break from the loop
            if(distance < _DISTANCE_THRESHOLD and
               similarity > _SIMILARITY_THRESHOLD):
                break

        # If a close enough song is found
        if(distance < _DISTANCE_THRESHOLD and
           similarity > _SIMILARITY_THRESHOLD):
            # Push it on the queue
            client.add(tmp_song_data["filename"])
            # Continue using latest pushed song as current song
            logging.info("Found a close song: %s. Distance is (%f, %f)." %
                         (tmp_song_data["filename"], distance, similarity))
            current_song_coords = tmp_song_data
            continue
        # If no song found, take the closest one
        else:
            logging.info("No close enough song found. Using %s. Distance is (%f, %f)." %
                         (closest_song[0]["filename"], closest_song[1],
                          closest_song[2]))
            current_song_coords = closest_song[0]
            client.add(closest_song[0]["filename"])
            continue
    conn.close()
    client.close()
    client.disconnect()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--queue-length", help="The number of items to add to the MPD playlist.", type=int)
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
        main_single(queue_length)
    elif args.album_based:
        main_album(queue_length)

