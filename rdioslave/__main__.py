from __future__ import absolute_import, division, print_function, unicode_literals

import getpass
import six

from .player import Player
from .rdio_web import RdioWebClient

def main():
    session_file = "rdio_session.json"
    api_client = RdioWebClient()
    try:
        api_client.read_session(session_file)
    except IOError:
        username = six.moves.input("Username: ")
        password = getpass.getpass()
        api_client.init_session(username, password)
        api_client.write_session(session_file)
    player = Player(api_client)
    player.run()

if __name__ == "__main__":
    main()
