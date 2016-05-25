Blissify
========

Blissify is a wrapper around Bliss
[Bliss](https://github.com/Polochon-street/bliss) to compute and store values
in an SQLite database.

It is done in an attempot to bind Bliss to MPD to be able to play
smooth mixes with MPD, _à la_ Grooveshark radio.

## Dependencies

To build it you will need `sqlite3`, plus the required
dependencies from `bliss` (see
[https://github.com/Polochon-street/bliss](https://github.com/Polochon-street/bliss)).


## Build

```
git clone --recursive https://github.com/phyks/blissify
cd blissify; mkdir build
cmake ..
make
```

This will build a `blissify` executable.


## Usage

This repo contains several codes and scripts.

## The main `blissify` executable

The main `blissify` executable can be used to compute the values necessary to
use Bliss for various song files and store them in a SQLite database.

This executable takes a first argument being the basepath and a list of
filenames relative to this basepath as argument. It will compute values using
Bliss and store them in a SQLite database located in
`$XDG_DATA_HOME/blissify/db.sqlite3` (defaults to
`~/.local/share/blissify/db.sqlite3`).

You can do whatever you want with this db afterwards.


## The MPD server-side script

In the `mpd/` folder of this repo, you will find a `server.py` script. This is
a simple Python script to easily build the database from your MPD music
library. It calls `blissify` under the hood, so note that the `blissify`
executable **SHOULD** be in your `$PATH`.

It takes a `mpd_root` argument to set the top path of your MPD music library.
You can use either

* `--full-rescan` to purge the db and perform a full scan of your MPD music
  library.
* `--rescan-errored` to scan failed files stored in database (from a previous
  run). This option is usable even if you do not use MPD.
* `--update` to perform an update based on new additions to the library.
* `--listen` to listen to MPD IDLE signals on database update and update the
  database accordingly in realtime.

Connection to your MPD server is handled by `$MPD_HOST` and `$MPD_PORT`
(defaulting to `localhost` and `6600`), as described in `mpc` man page.


_Note_: This step can be quite long. It took me around 50 hours to build the
database for a library with 50k songs.

## The MPD client-side script

Once you have built the database, you may want to play a continuous mix with
MPD. This is the purpose of the `client.py` script in `mpd/×` folder.

This script also uses the same environment variables as `mpc` does to connect to your MPD server.

_Note_: This script needs to have access to the database you built previously.
Then, you should either copy the database on the client (in the same
`$XDG_DATA_HOME/blissify` folder) or run it on the server.

It takes a single (optional) argument which is the number of songs to add to the playlist. Default is 20.

It builds a continuous mix starting from the latest song in your playlist. If your playlist is empty, it will start from a random song.

_Note_: If random mode is enabled in MPD, the script will warn you about it. Indeed, in this case, the mix is no longer continuous.


## The cache building script

Finally, in `scripts` folder, you will find a Python script `build_cache.py` to
build the distances cache.

Whenever you want to create a continuous mix, the client script will iterate
through your music library, compute pairwise distances and take a close enough
song. These computed distances are stored in the database as a cache, to
generate a playlist faster the next time.

This `build_cache.py` script can be used to precompute the pairwise distances
and build the cache, if you are willing to make some extra computation to
generate mixes faster.
