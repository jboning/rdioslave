from __future__ import absolute_import, division, print_function, unicode_literals

import json
import random
import re
import requests
import six

from tornado import gen, httpclient, ioloop, websocket

from .util import add_future

class RdioWebClient(object):
    SERVER = "www.rdio.com"
    API_VERSION = "1"
    client_version = 20130124

    class ApiFailureException(Exception):
        pass

    def __init__(self):
        self.session_initialized = False
        self.player_id = "_rdioslave_" + ("%06d" % random.randint(0, 1000000))

        # user auth session
        self.cookies = {}
        self.authorization_key = None
        self.user_key = None

        # client state
        self.ws = None
        self.pubsub_data = None

    ####################
    # Session
    ####################

    def has_session(self):
        if not self.session_initialized:
            return False
        try:
            self.current_user_sync()
        except self.ApiFailureException:
            return False
        return True

    def init_session(self, username, password):
        def get_auth_key(page):
            match = re.search(r'"authorizationKey": "([^"]*)"', page)
            assert match, "could not find authorizationKey: rdio login changed!"
            return match.group(1)

        resp = requests.get("https://%s/account/signin/" % self.SERVER)
        self.cookies['r'] = resp.cookies['r']
        self.authorization_key = get_auth_key(resp.text)

        result = self.sign_in_sync(username, password)

        # redirect url sends us a cookie and then 302s to home
        resp = requests.get(result['redirect_url'])
        self.cookies['r'] = resp.history[0].cookies['r']
        self.authorization_key = get_auth_key(resp.text)

        resp = self.current_user_sync()
        self.user_key = resp['key']

        self.session_initialized = True

    def write_session(self, file_path):
        data = {
            'cookies': self.cookies,
            'authorization_key': self.authorization_key,
            'user_key': self.user_key,
        }
        with open(file_path, "wt") as f:
            f.write(json.dumps(data))

    def read_session(self, file_path):
        with open(file_path, "rt") as f:
            data = json.loads(f.read())

        # json unicodifies everything, so we need to convert back to str
        for k, v in six.iteritems(data['cookies']):
            self.cookies[k.encode('ascii')] = str(v.encode('ascii'))
        self.authorization_key = data['authorization_key'].encode('ascii')
        self.user_key = data['user_key'].encode('ascii')

        self.session_initialized = True
        assert self.has_session()

    ####################
    # PubSub
    ####################

    @gen.coroutine
    def setup_pubsub(self, on_message):
        self.pubsub_data = yield self.pubsub_info()
        host = self.pubsub_data['servers'][0]
        self.ws = yield websocket.websocket_connect("ws://%s" % host)

        add_future(self.pubsub_read(on_message))

        self.connect()

    def connect(self):
        assert self.ws
        caps = {'player': {'canRemote': True, 'name': self.player_id}}
        ws_msg = "CONNECT %s|%s" % (self.pubsub_data['token'], json.dumps(caps))
        print("sending on websocket: %s" % ws_msg)
        self.ws.write_message(ws_msg)

    def pub(self, channel, message):
        assert self.ws
        if not isinstance(message, six.string_types):
            message = json.dumps(message)
        ws_msg = "PUB %s/%s|%s" % (self.user_key, channel, message)
        print("sending on websocket: %s" % ws_msg)
        self.ws.write_message(ws_msg)

    def sub(self, channel):
        assert self.ws
        ws_msg = "SUB %s/%s" % (self.user_key, channel)
        print("sending on websocket: %s" % ws_msg)
        self.ws.write_message(ws_msg)

    @gen.coroutine
    def pubsub_read(self, on_message):
        while True:
            message = yield self.ws.read_message()
            print("[PubSub] got message: %s" % message)
            if message is None:
                # Socket closed; set up pubsub again. Probably racy (we might
                # try to pub while there's no websocket there).
                yield self.setup_pubsub(on_message)
                return
            on_message(message)

    ####################
    # API call helpers
    ####################

    def _encode_params(self, params):
        # This is kind of dubious
        return requests.models.RequestEncodingMixin._encode_params(params)

    def _construct_api_request(self, method, params, secure, gag_debug):
        if params is None:
            params = {}
        params['v'] = self.client_version
        params['_authorization_key'] = self.authorization_key
        params['method'] = method
        protocol = "https" if secure else "http"
        url = "%s://%s/api/%s/%s" % (protocol, self.SERVER, self.API_VERSION, method)
        if not gag_debug:
            print(json.dumps(params, indent=4))
        request = httpclient.HTTPRequest(
            url,
            method="POST",
            headers={
                "Cookie": "; ".join(["%s=%s" % it for it in six.iteritems(self.cookies)]),
                "Content-Type": "application/x-www-form-urlencoded",
            },
            body=self._encode_params(params),
        )
        return request

    def _process_api_response(self, response):
        if response.code != 200:
            raise self.ApiFailureException(str(response.code))
        response_parsed = json.loads(response.body)
        if response_parsed['status'] != "ok":
            raise self.ApiFailureException(json.dumps(response_parsed, indent=4))
        return response_parsed['result']

    @gen.coroutine
    def call_api(self, method, params=None, secure=False, gag_debug=False):
        request = self._construct_api_request(method, params, secure, gag_debug)
        response = yield httpclient.AsyncHTTPClient().fetch(request)
        raise gen.Return(self._process_api_response(response))

    def call_api_sync(self, method, params=None, secure=False, gag_debug=False):
        request = self._construct_api_request(method, params, secure, gag_debug)
        response = httpclient.HTTPClient().fetch(request)
        return self._process_api_response(response)

    ####################
    # Rdio API
    ####################

    def current_user_sync(self):
        return self.call_api_sync("currentUser")

    @gen.coroutine
    def generate_station(self, station_key, exclude, extras=None):
        params = {
            "station_key": station_key,
            "exclude": ",".join(exclude)
        }
        if extras is not None:
            params["extras"] = ",".join(extras)
        ret = yield self.call_api("generateStation", params)
        raise gen.Return(ret)

    @gen.coroutine
    def get(self, keys, extras=None):
        assert not isinstance(keys, six.string_types)
        params = {
            "keys": ",".join(keys),
        }
        if extras is not None:
            params["extras"] = ",".join(extras)
        ret = yield self.call_api("get", params)
        raise gen.Return(ret)

    @gen.coroutine
    def get_playback_info(self, key, manual_play=True, type="flash",
                          player_name=None, requires_unlimited=False):
        if player_name is None:
            player_name = self.player_id
        data = {
            'key': key,
            'manualPlay': manual_play,
            'type': type,
            'playerName': player_name,
            'requiresUnlimited': requires_unlimited,
        }
        ret = yield self.call_api("getPlaybackInfo", data)
        raise gen.Return(ret)

    @gen.coroutine
    def get_player_state(self):
        ret = yield self.call_api("getPlayerState")
        raise gen.Return(ret)

    @gen.coroutine
    def pubsub_info(self):
        ret = yield self.call_api("pubsubInfo")
        raise gen.Return(ret)

    @gen.coroutine
    def save_player_state(self, player_state=None, queue=None):
        assert any((player_state is not None, queue is not None))
        params = {}
        if player_state is not None:
            params["player_state"] = json.dumps(player_state)
        if queue is not None:
            params["queue"] = json.dumps(queue)
        ret = yield self.call_api("savePlayerState", params)
        raise gen.Return(ret)

    def sign_in_sync(self, username, password, remember=1, next_url=""):
        params = {
            'username': username,
            'password': password,
            'remember': remember,
            'nextUrl': next_url,
        }
        return self.call_api_sync("signIn", params, secure=True, gag_debug=True)
