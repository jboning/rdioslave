from __future__ import absolute_import, division, print_function, unicode_literals

import argparse
import getpass
import six

from .player import Player
from .rdio_web import RdioWebClient

def get_client_session(session_file):
    api_client = RdioWebClient()
    try:
        api_client.read_session(session_file)
    except IOError:
        username = six.moves.input("Username: ")
        password = getpass.getpass()
        api_client.init_session(username, password)
        api_client.write_session(session_file)
    return api_client

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('-c', '--config', default="rdio_session.json")
    parser.add_argument('--stream-player', default="external", choices=["external", "mock"])
    args = parser.parse_args()

    api_client = get_client_session(args.config)
    player = Player(api_client, use_stream_player=args.stream_player)
    player.run()

if __name__ == "__main__":
    main()
