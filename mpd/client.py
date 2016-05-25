#!/usr/bin/env python3
"""
This is a client for MPD to generate a random playlist starting from the last
song of the current playlist and iterating using values computed using Bliss.

MPD connection settings are taken from environment variables, following MPD_HOST
and MPD_PORT scheme described in `mpc` man.

You can pass an integer argument to the script to change the length of the
generated playlist (default is to add 20 songs).
"""
import logging
import math
import os
import random
import sqlite3
import subprocess
import sys

from mpd import MPDClient

# TODO: Timeout

logging.basicConfig(level=logging.INFO)

_QUEUE_LENGTH = 20
_DISTANCE_THRESHOLD = 4.0
_SIMILARITY_THRESHOLD = 0.95

if "XDG_DATA_HOME" in os.environ:
    _BLISSIFY_DATA_HOME = os.path.expandvars("$XDG_DATA_HOME/blissify")
else:
    _BLISSIFY_DATA_HOME = os.path.expanduser("~/.local/share/blissify")


def main(queue_length):
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
    # Connect to db
    db_path = os.path.join(_BLISSIFY_DATA_HOME, "db.sqlite3")
    logging.debug("Using DB path: %s." % (db_path,))
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute('pragma foreign_keys=ON')
    cur = conn.cursor()

    # Ensure random is not enabled
    status = client.status()
    if status["random"] != 0:
        logging.warning("Random mode is enabled. Are you sure you want it?")

    # Take the last song from current playlist and iterate from it
    playlist = client.playlist()
    if len(playlist) > 0:
        current_song = playlist[-1].replace("file:", "").strip()
    # If current playlist is empty
    else:
        # Add a random song to start with
        all_songs = [x["file"] for x in client.listall() if "file" in x]
        current_song = random.choice(all_songs)
        client.add(current_song)
    logging.info("Currently played song is %s." % (current_song,))

    # Get current song coordinates
    cur.execute("SELECT id, tempo, amplitude, frequency, attack, filename FROM songs WHERE filename=?", (current_song,))
    current_song_coords = cur.fetchone()
    if current_song_coords is None:
        logging.warning("Current song %s is not in db. You should update the db." %
                        (current_song,))
        client.close()
        client.disconnect()
        sys.exit(1)

    for i in range(queue_length):
        # Get cached distances from db
        cur.execute(
            "SELECT id, filename, distance, similarity, tempo, amplitude, frequency, attack FROM (SELECT s2.id AS id, s2.filename AS filename, s2.tempo AS tempo, s2.amplitude AS amplitude, s2.frequency AS frequency, s2.attack AS attack, distances.distance AS distance, distances.similarity AS similarity FROM distances INNER JOIN songs AS s1 ON s1.id=distances.song1 INNER JOIN songs AS s2 on s2.id=distances.song2 WHERE s1.filename=? UNION SELECT s1.id as id, s1.filename AS filename, s1.tempo AS tempo, s1.amplitude AS amplitude, s1.frequency AS frequency, s1.attack AS attack, distances.distance as distance, distances.similarity AS similarity FROM distances INNER JOIN songs AS s1 ON s1.id=distances.song1 INNER JOIN songs AS s2 on s2.id=distances.song2 WHERE s2.filename=?) ORDER BY distance ASC",
            (current_song_coords["filename"], current_song_coords["filename"]))
        cached_distances = [row
                            for row in cur.fetchall()
                            if ("file: %s" % (row["filename"],)) not in client.playlist()]
        cached_distances_songs = [i["filename"] for i in cached_distances]

        # If distance to closest song is ok, just add the song
        if len(cached_distances) > 0:
            if(cached_distances[0]["distance"] < _DISTANCE_THRESHOLD and
	       cached_distances[0]["similarity"] > _SIMILARITY_THRESHOLD):
                # Push it on the queue
                client.add(cached_distances[0]["filename"])
                # Continue using latest pushed song as current song
                logging.info("Using cached distance. Found %s. Distance is (%f, %f)." %
                             (cached_distances[0]["filename"],
                              cached_distances[0]["distance"],
                              cached_distances[0]["similarity"]))
                current_song_coords = cached_distances[0]
                continue

        # Get all other songs coordinates
        closest_song = None
        cur.execute("SELECT id, tempo, amplitude, frequency, attack, filename FROM songs")
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
            # TODO: Find a better heuristic?
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
    queue_length = _QUEUE_LENGTH
    if len(sys.argv) > 1:
        try:
            queue_length = int(sys.argv[1])
        except ValueError:
            sys.exit("Usage: %s [PLAYLIST_LENGTH]" % (sys.argv[0],))
    main(queue_length)
