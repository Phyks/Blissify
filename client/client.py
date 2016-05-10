#!/usr/bin/env python3
import logging
import math
import os
import sqlite3
import subprocess
import sys

logging.basicConfig(level=logging.INFO)

_QUEUE_LENGTH = 100
# TODO: Use cosine similarity as well
_DISTANCE_THRESHOLD = 4.0

if "XDG_DATA_HOME" in os.environ:
    _MPDBLISS_DATA_HOME = os.path.expandvars("$XDG_DATA_HOME/mpdbliss")
else:
    _MPDBLISS_DATA_HOME = os.path.expanduser("~/.local/share/mpdbliss")


def main():
    mpd_queue = []
    db_path = os.path.join(_MPDBLISS_DATA_HOME, "db.sqlite3")
    logging.debug("Using DB path: %s." % (db_path,))
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute('pragma foreign_keys=ON')
    cur = conn.cursor()

    current_song = subprocess.check_output(
        ["mpc", "current", '--format',  '"%file%"'])
    current_song = current_song.decode("utf-8").strip('" \r\n\t')
    if current_song is "":
        logging.warning("Currently played song could not be found.")
        sys.exit(1)
    logging.info("Currently played song is %s." % (current_song,))

    # Get current song coordinates
    cur.execute("SELECT id, tempo, amplitude, frequency, attack, filename FROM songs WHERE filename=?", (current_song,))
    current_song = cur.fetchone()
    if current_song is None:
        logging.warning("Current song %s is not in db. You should update the db." %
                        (current_song["filename"],))
        sys.exit(1)

    for i in range(_QUEUE_LENGTH):
        # Append current song to the mpd queue to avoid duplicates
        mpd_queue.append(current_song["filename"])
        # Get cached distances from db
        cur.execute(
            "SELECT id, filename, distance FROM (SELECT s2.id AS id, s2.filename AS filename, distances.distance AS distance FROM distances INNER JOIN songs AS s1 ON s1.id=distances.song1 INNER JOIN songs AS s2 on s2.id=distances.song2 WHERE s1.filename=? UNION SELECT s1.id as id, s1.filename AS filename, distances.distance as distance FROM distances INNER JOIN songs AS s1 ON s1.id=distances.song1 INNER JOIN songs AS s2 on s2.id=distances.song2 WHERE s2.filename=?) ORDER BY distance ASC",
            (current_song["filename"], current_song["filename"]))
        cached_distances = [row
                            for row in cur.fetchall()
                            if row["filename"] not in mpd_queue]
        cached_distances_songs = [i["filename"] for i in cached_distances]

        # If distance to closest song is ok, just add the song
        if len(cached_distances) > 0:
            if cached_distances[0]["distance"] < _DISTANCE_THRESHOLD:
                # Push it on the queue
                subprocess.check_call(["mpc", "add",
                                       cached_distances[0]["filename"]])
                # Continue using latest pushed song as current song
                logging.info("Using cached distance. Found %s. Distance is %f." %
                             (current_song["filename"], cached_distances[0]["distance"]))
                current_song = cached_distances[0]
                continue

        # Get all other songs coordinates
        closest_song = None
        cur.execute("SELECT id, tempo, amplitude, frequency, attack, filename FROM songs")
        for tmp_song_data in cur.fetchall():
            if(tmp_song_data["filename"] == current_song["filename"] or
               tmp_song_data["filename"] in cached_distances_songs or
               tmp_song_data["filename"] in mpd_queue):
                # Skip current song and already processed songs
                logging.debug("Skipping %s." % (tmp_song_data["filename"]))
                continue
            # Compute distance
            distance = math.sqrt(
                (current_song["tempo"] - tmp_song_data["tempo"])**2 +
                (current_song["amplitude"] - tmp_song_data["amplitude"])**2 +
                (current_song["frequency"] - tmp_song_data["frequency"])**2 +
                (current_song["attack"] - tmp_song_data["attack"])**2
            )
            logging.debug("Distance between %s and %s is %f." %
                          (current_song["filename"],
                           tmp_song_data["filename"], distance))
            # Store distance in db cache
            try:
                logging.debug("Storing distance in database.")
                conn.execute(
                    "INSERT INTO distances(song1, song2, distance) VALUES(?, ?, ?)",
                    (current_song["id"], tmp_song_data["id"], distance))
                conn.commit()
            except sqlite3.IntegrityError:
                logging.warning("Unable to insert distance in database.")
                conn.rollback()

            # If distance is ok, just add the song
            if distance < _DISTANCE_THRESHOLD:
                # Push it on the queue
                subprocess.check_call(["mpc", "add", tmp_song_data["filename"]])
                # Continue using latest pushed song as current song
                logging.info("Found a close song: %s. Distance is %f." %
                             (tmp_song_data["filename"], distance))
                current_song = tmp_song_data
                break
            elif closest_song is None or distance < closest_song[1]:
                closest_song = (tmp_song_data, distance)
        # If no song found, take the closest one
        logging.info("No close enough song found. Using %s. Distance is %f." %
                     (closest_song[0]["filename"], closest_song[1]))
        current_song = closest_song[0]
        subprocess.check_call(["mpc", "add", closest_song[0]["filename"]])
    conn.close()


if __name__ == "__main__":
    main()
