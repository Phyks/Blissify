#!/usr/bin/env python3
import logging
import math
import os
import sqlite3

logging.basicConfig(level=logging.DEBUG)

if "XDG_DATA_HOME" in os.environ:
    _BLISSIFY_DATA_HOME = os.path.expandvars("$XDG_DATA_HOME/blissify")
else:
    _BLISSIFY_DATA_HOME = os.path.expanduser("~/.local/share/blissify")


def main():
    db_path = os.path.join(_BLISSIFY_DATA_HOME, "db.sqlite3")
    logging.debug("Using DB path: %s." % (db_path,))
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute('pragma foreign_keys=ON')
    cur = conn.cursor()

    # Get cached distances from db
    cur.execute("SELECT song1, song2, distance, similarity FROM distances")
    cached_distances = cur.fetchall()

    # Get all songs
    cur.execute("SELECT id, tempo, amplitude, frequency, attack, filename FROM songs")
    all_songs = cur.fetchall()

    for i in range(len(all_songs)):
        for j in range(i + 1, len(all_songs)):
            song1 = all_songs[i]
            song2 = all_songs[j]
            is_cached = len([i for i in cached_distances
                             if(i["song1"] == song1["id"] and
                                i["song2"] == song2["id"]) or
                             (i["song1"] == song2["id"] and
                              i["song2"] == song1["id"])]) > 0
            if is_cached:
                # Pass pair if cached value is already there
                continue
            # Compute distance
            distance = math.sqrt(
                (song1["tempo"] - song2["tempo"])**2 +
                (song1["amplitude"] - song2["amplitude"])**2 +
                (song1["frequency"] - song2["frequency"])**2 +
                (song1["attack"] - song2["attack"])**2
            )
            similarity = (
                (song1["tempo"] * song2["tempo"] +
                 song1["amplitude"] * song2["amplitude"] +
                 song1["frequency"] * song2["frequency"] +
                 song1["attack"] * song2["attack"]) /
                (
                    math.sqrt(
                        song1["tempo"]**2 +
                        song1["amplitude"]**2 +
                        song1["frequency"]**2 +
                        song1["attack"]**2) *
                    math.sqrt(
                        song2["tempo"]**2 +
                        song2["amplitude"]**2 +
                        song2["frequency"]**2 +
                        song2["attack"]**2)
                )
            )

            logging.debug("Distance between %s and %s is (%f, %f)." %
                          (song1["filename"], song2["filename"], distance,
                           similarity))
            # Store distance in db cache
            try:
                logging.debug("Storing distance in database.")
                conn.execute(
                    "INSERT INTO distances(song1, song2, distance, similarity) VALUES(?, ?, ?, ?)",
                    (song1["id"], song2["id"], distance, similarity))
                conn.commit()
                # Update cached_distances list
                cached_distances.append({
                    "song1": song1["id"],
                    "song2": song2["id"],
                    "distance": distance,
                    "similarity": similarity
                })
            except sqlite3.IntegrityError:
                logging.warning("Unable to insert distance in database.")
                conn.rollback()
    # Close connection
    conn.close()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
