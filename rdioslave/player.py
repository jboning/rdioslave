from __future__ import absolute_import, division, print_function, unicode_literals

import copy
import json
import sys

from tornado import gen, ioloop, process

from .stream_player import MockStreamPlayer, StreamPlayer
from .util import add_future, d


ALBUMISH_TYPES = frozenset(("a", "al", "p"))
STATION_TYPES = frozenset(("lr", "rr", "h", "e", "tr", "c"))


class Player(object):
    def __init__(self, api_client, use_stream_player="external"):
        self.client = api_client

        if use_stream_player == "external":
            self.stream_player = StreamPlayer(self.on_stream_ended)
        elif use_stream_player == "mock":
            self.stream_player = MockStreamPlayer()
        else:
            assert False

        self.queue = None
        self.player_state = None
        self.is_master = False
        self.is_active = False

    def run(self):
        add_future(self.launch())
        ioloop.IOLoop.instance().start()

    @gen.coroutine
    def launch(self):
        yield self.client.setup_pubsub(self.pubsub_message_handler)
        yield self.get_state()
        yield self.play_current_track()

    def pubsub_message_handler(self, msg):
        op, _, content = msg.partition(' ')
        if op == "PUB":
            channel, pipe, message = content.partition('|')
            assert pipe == '|'
            user, slash, user_channel = channel.partition('/')

            if user != self.client.user_key:
                print("unexpected user!!! %s" % user)
                return

            message = json.loads(message)
            event = message['event']

            if (user_channel, event) == ("private", "remote"):
                command = message["command"]
                print(("got remote command: %s" % command["type"]))
                if command["type"] == "togglePause":
                    add_future(self.toggle_pause())
                elif command["type"] == "next":
                    add_future(self.next_track())
                elif command["type"] == "previous":
                    add_future(self.previous_track())
                elif command["type"] == "playSource":
                    add_future(self.play_source(command))
                elif command["type"] == "playQueuedSource":
                    add_future(self.play_queued_source(command))
                elif command["type"] == "queueSource":
                    add_future(self.queue_source(command))
                elif command["type"] == "set":
                    key = command["key"] # station
                    value = command["value"]
                    if key == "sourcePosition":
                        self.player_state['currentSource']['currentPosition'] = value
                        add_future(self.play_current_track())
                else:
                    assert False, "unrecognized remote command: %s" % json.dumps(command, indent=4)
            elif (user_channel, event) == ("player", "masterQuery"):
                self.publish_master_state()
            elif (user_channel, event) == ("player", "masterPlayer"):
                if message["name"] != self.client.player_id:
                    self.stream_player.kill_stream()
                    sys.exit(0) # TODO: need any more cleanup?
            else:
                print("===== UNRECOGNIZED MESSAGE =====")
                print(("channel: %s" % channel))
                d(message)
                print("================================")

        elif op == "CONNECTED":
            self.client.sub("private")
            self.client.sub("presence")
            self.client.sub("fields")
            self.client.sub("player")

            if not self.is_master:
                self.is_active = True
                self.publish_master_state() # claim control of the world
                self.is_master = True
                add_future(self.play_current_track())

        else:
            raise AssertionError("unexpected op %s" % op)

    def on_stream_ended(self):
        print("STREAM ENDED")
        add_future(self.next_track())

    def publish_master_state(self):
        self.client.pub("player",
                        {"event":"masterPlayer", 
                         "name": self.client.player_id,
                         "playState": 1 if self.is_active else 0,
                         "volume": 1,
                        })

    @gen.coroutine
    def play_current_track(self):
        if not all((self.player_state, self.is_master)):
            return

        # TODO: it looks like the player state we get from the server doesn't
        # include how far into the track we are. If we are running in the
        # background, we could probably watch the state changes on the pubsub
        # server and keep track of this ourselves.

        source = self.player_state['currentSource']
        if source is None:
            return
        if source['type'] in (ALBUMISH_TYPES | STATION_TYPES):
            track_key = source['tracks']['items'][source['currentPosition']]['key']
        elif source['type'] == "t":
            track_key = source['key']
        else:
            assert False, "not implemented!"

        add_future(self.save_state())
        playback_info = yield self.client.get_playback_info(track_key)
        self.stream_player.play_stream(playback_info['surl'])

    @gen.coroutine
    def get_state(self):
        result = yield self.client.get_player_state()
        print('RESULT QUEUE:')
        d(result['queue'])
        self.queue = result['queue']['data']
        self.player_state = result['playerState']
        d(self.player_state)

    @gen.coroutine
    def save_state(self):
        # TODO: currently save player state and queue every time. Would be more
        # efficient to save state more granularly.
        print("saving state")
        #print "complete state:"
        #d(self.player_state)
        def state_to_save_for_obj(s):
            if s is None:
                return None
            state = {'key': s['key']}
            if s['type'] in ALBUMISH_TYPES | STATION_TYPES:
                state['currentPosition'] = s['currentPosition']
            if s['type'] in STATION_TYPES:
                state['tracks'] = [track['key'] for track in s['tracks']['items']]
            return state
        source = self.player_state['currentSource']
        state_to_save = {
            'shuffle': False,
            'repeat': 0,
            'currentSource': state_to_save_for_obj(self.player_state['currentSource']),
            'station': state_to_save_for_obj(self.player_state['station']),
        }
        print("saving:")
        d(state_to_save)
        queue_to_save = self.queue
        d(queue_to_save)
        ret = yield self.client.save_player_state(player_state=state_to_save, queue=self.queue)

    @gen.coroutine
    def toggle_pause(self):
        if self.is_active:
            # TODO: pause don't stop
            self.stop_player()
        else:
            self.is_active = True
            self.publish_master_state()
            yield self.play_current_track()

    def stop_player(self):
        self.is_active = False
        self.publish_master_state()
        self.stream_player.kill_stream()

    @gen.coroutine
    def play_source(self, command):
        if not self.is_active:
            self.is_active = True
            self.publish_master_state()
        key = command["key"]

        # If we already have the source, don't fetch it from the server. This
        # is not just an optimization, but for stations, actually necessary to
        # avoid losing the currently shown list of tracks.
        if (self.player_state['currentSource'] and
                self.player_state['currentSource']['key'] == key):
            source = self.player_state['currentSource']
        elif (self.player_state['station'] and
                self.player_state['station']['key'] == key):
            source = copy.deepcopy(self.player_state['station'])
        else:
            objs_by_key = yield self.client.get([key], ["tracks"])
            source = objs_by_key[key]
        d(source)

        if source['type'] in ALBUMISH_TYPES:
            index = command.get('index', 0)
            source['currentPosition'] = index
            self.player_state['currentSource'] = source
        elif source['type'] in STATION_TYPES:
            index = command.get('index') or source.get('currentPosition') or 0
            source['currentPosition'] = index
            self.player_state['station']['currentPosition'] = index
            self.player_state['currentSource'] = source
        elif source['type'] == "t":
            self.player_state['currentSource'] = source
        else:
            d(source)
            assert False, "unhandled object type %s (above)" % source['type']
        yield self.play_current_track()

    @gen.coroutine
    def play_queued_source(self, command):
        source = self.queue.pop(command.pop("queueIndex"))
        if "sourceIndex" in command:
            command["index"] = command.pop("sourceIndex")
        command["key"] = source["key"]
        yield self.play_source(command) # XXX gross

    @gen.coroutine
    def queue_source(self, command):
        key = command["key"]
        self.queue.append({"key": key})
        yield self.save_state()

    @gen.coroutine
    def next_track(self):
        print()
        print("CHANGING TRACKS: NEXT")
        print()
        print("state before:")
        d(self.player_state)
        source = self.player_state['currentSource']
        if source is None:
            return
        if source['type'] in ALBUMISH_TYPES:
            source['currentPosition'] += 1
            if source['currentPosition'] >= source['tracks']['total']:
                if self.queue:
                    # TODO: eliminate this latency by preloading sources in queue
                    key = self.queue.pop(0)["key"]
                    result = yield self.client.get([key], ["tracks"])
                    source = result[key]
                    self.player_state['currentSource'] = source
                    if source['type'] in (ALBUMISH_TYPES | STATION_TYPES):
                        self.player_state['currentSource']['currentPosition'] = 0
                elif self.player_state['station']:
                    # switch to the station
                    self.player_state['currentSource'] = copy.deepcopy(self.player_state['station'])
                    if 'currentPosition' not in self.player_state['currentSource']:
                        self.player_state['currentSource']['currentPosition'] = 0
                else:
                    # Out of things to play. Stop.
                    self.stop_player()
                    self.player_state['currentSource'] = None
                    yield self.save_state()
                    return
        elif source['type'] in STATION_TYPES:
            station = self.player_state['station']
            if source['currentPosition'] < 2:
                source['currentPosition'] += 1
                station['currentPosition'] = source['currentPosition']
            else:
                exclude = [track['key'] for track in source['tracks']['items']]
                result = yield self.client.generate_station(source['key'], exclude)
                new_track = result['tracks']['items'][0]
                new_station_tracks = source['tracks']['items'][1:] + [new_track]
                source['tracks']['items'] = new_station_tracks
                station['tracks']['items'] = new_station_tracks
        else:
            d(source)
            assert False, "unhandled object type %s (above)" % source['type']

        yield self.play_current_track()

    @gen.coroutine
    def previous_track(self):
        source = self.player_state['currentSource']
        if source is None:
            return
        if source['type'] in (ALBUMISH_TYPES | STATION_TYPES):
            if source['currentPosition'] == 0:
                # TODO: maybe we could be clever about history here
                self.stop_player()
                return
            source['currentPosition'] -= 1
        else:
            d(source)
            assert False, "unhandled object type %s (above)" % source['type']

        yield self.play_current_track()
