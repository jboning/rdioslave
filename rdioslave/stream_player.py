from __future__ import absolute_import, division, print_function, unicode_literals

import subprocess
import sys

from tornado import ioloop, process

class MockStreamPlayer(object):
    def play_stream(self, surl):
        print("--- WOULD PLAY STREAM ---")
        print("--- %s ---" % surl)
    def kill_stream(self):
        print("--- WOULD KILL STREAM ---")
        pass

class StreamPlayer(object):
    def __init__(self, on_stream_ended):
        self.download_p = None
        self.play_p = None
        self.on_stream_ended = on_stream_ended

    def play_stream(self, info):
        self.kill_stream()
        download_cmd = ["rtmpdump",
                        "-r", "rtmpe://%s%s" % (info['streamHost'], info['streamApp']),
                        "-y", "mp3:" + info['surl'],
                        "-o", "-",
                       ]
        play_cmd = ["mplayer", "-cache", "2048", "-quiet", "-"]
        self.download_p = process.Subprocess(
                download_cmd, stdout=subprocess.PIPE, io_loop=ioloop.IOLoop.instance())
        self.play_p = process.Subprocess(
                play_cmd, stdin=self.download_p.stdout, io_loop=ioloop.IOLoop.instance())
        self.play_p.set_exit_callback(self.stream_ended_cb(self.play_p))

    def kill_stream(self):
        if self.play_p:
            play_p = self.play_p
            self.play_p = None
            try:
                play_p.proc.terminate()
            except OSError:
                pass
        if self.download_p:
            download_p = self.download_p
            self.download_p = None
            try:
                download_p.proc.terminate()
            except OSError:
                pass

    def stream_ended_cb(self, cb_play_p):
        def callback(ret):
            if self.play_p != cb_play_p:
                # we killed the stream... don't call the callback
                return
            else:
                self.kill_stream()
                self.on_stream_ended()
        return callback
