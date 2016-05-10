MPDBliss
========

MPDBliss is an attempt at binding
[Bliss](https://github.com/Polochon-street/bliss) to MPD to be able to play
smooth mixes with MPD, _à la_ Grooveshark radio.

## Dependencies

To build it you will need `sqlite3` and `libmpdclient`, plus the required
dependencies from `bliss` (see
[https://github.com/Polochon-street/bliss](https://github.com/Polochon-street/bliss)).


## Build

```
git clone --recursive https://github.com/phyks/mpdbliss
cd mpdbliss; mkdir build
cmake ..
make
```

This will build a `mpdbliss` executable.


## Usage

`mpdbliss` is made of two components. First one, `mpdbliss`, has to run on the
MPD server machine (or at least have access to the music files) and will build
and maintain a parallel database of song "features" and distances between
them, as computed by `bliss`. This will be stored in
`$XDG_DATA_HOME/mpdbliss/` (defaults to `~/.local/share/mpdbliss`). Second one
is a client, to create playlist based on the currently playing song.
`client.sh` script at the root of this repository is an example of such a
script. Such client script needs to have access to the database build in first
step.

See `mpdbliss --help` for up to date doc.

_Note_: `mpdbliss` supports the `MPD_HOST`/`MPD_PORT` environment variables.
You can overload them passing it command-line argument. Passwords should be
provided in the host string following the standard MPD syntax.

There are basically 3 modes of operation:
* `--rescan` which will trigger a full rescan of your MPD database and
  recreate the associated bliss database.
* `--update` which will do the same, but will only consider newly added
  musics.
* Without any flag, `mpdbliss` will listen for MPD IDLE protocol, and trigger
  an update of the database whenever the MPD database is modified.

Typical usage would be to run a `--rescan` first, and then either do periodic
`--update` or let it run listening at MPD IDLE protocol to maintain MPD
database and `mpdbliss` database in sync.


Check the `client.sh` script for an example client script to build smooth MPD
playlists.
out any flag, `mpdbliss` will listen for MPD IDLE protocol, and trigger
  an update of the database whenever the MPD database is modified.

Typical usage would be to run a `--rescan` first, and then either do periodic
`--update` or let it run listening at MPD IDLE protocol to maintain MPD
database and `mpdbliss` database in sync.


Check the `client/client.py` script for an example client script to build smooth MPD
playlists.
