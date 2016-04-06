#!/bin/sh

QUEUE_LENGTH=100

if [ -z "$XDG_DATA_HOME" ]; then
    mpdbliss_data_home="$HOME/.local/share/mpdbliss"
else
    mpdbliss_data_home="$XDG_DATA_HOME/mpdbliss"
fi

current_song=`mpc current --format "%file%"`
current_song="bad/_Compilations/8 Mile_ Music From and Inspired by the Motion Picture/01 - Lose Yourself.mp3"
for i in {1..$QUEUE_LENGTH}; do
    # Find closest song
    closest_song=`sqlite3 "$mpdbliss_data_home/db.sqlite3" "SELECT filename FROM (SELECT s2.filename AS filename, distances.distance AS distance FROM distances INNER JOIN songs AS s1 ON s1.id=distances.song1 INNER JOIN songs AS s2 on s2.id=distances.song2 WHERE s1.filename='$current_song' UNION SELECT s1.filename AS filename, distances.distance as distance FROM distances INNER JOIN songs AS s1 ON s1.id=distances.song1 INNER JOIN songs AS s2 on s2.id=distances.song2 WHERE s2.filename=\"$current_song\") ORDER BY distance ASC LIMIT 1"`
    if [ ! -z "$closest_song" ]; then
        # Push it on the queue
        mpc add "$closest_song" 2>&1 > /dev/null
        # Continue using latest pushed song as current song
        current_song="$closest_song"
        # Note: if song could not be found by mpd, it is just not added to the
        # queue and skipped
    fi
done
