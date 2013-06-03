# rdioslave

An interfaceless Rdio client for use with Remote Control Mode.

---

Installation:

    $ git clone https://github.com/jboning/rdioslave
    $ virtualenv env
    $ env/bin/pip install ./rdioslave

Usage:

    $ env/bin/rdioslave

You will be prompted for your username and password the first time you run
rdioslave; it will write your session to `rdio_session.json` in your current
directory, and subsequent runs will use the stored session.

When rdioslave starts, it will take control of your Rdio session and begin
playback, and you can control it from Rdio's web interface, which should
indicate that it is in Remote Control Mode. rdioslave will continue running
until you override it by clicking "Play here instead" (or by launching another
instance of rdioslave).

### Compatibility

rdioslave has only been tested on Python 2.7, but it should be compatible with
Python 3 (`2to3 -x future` reports no problems). Compatibility with lower
versions is unknown; `from __future__ import with_statement` might do the job.

### Dependencies

 - Python packages: tornado, requests, six
 - Programs in your PATH: rtmpdump, mplayer

### Caveats

 - Remote volume control is not implemented.
 - Transitions between tracks are slightly more gapful than usual.
 - When resuming from pause, rdioslave will play from the beginning of the track.
