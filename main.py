import signal

import fuse
from fuse import Fuse

fuse.fuse_python_api = (0, 2)

class SlackEmojiFS(Fuse):
    pass

def main():
    usage="""
Userspace Slack Emoji Filesystem

""" + Fuse.fusage
    server = SlackEmojiFS(
        version="%prog " + fuse.__version__,
        usage=usage,
        dash_s_do='setsingle',
    )
    server.parse(errex=1)

    old_sigint = signal.signal(signal.SIGINT, signal.SIG_DFL)
    try:
        server.main()
    finally:
        signal.signal(signal.SIGINT, old_sigint)

if __name__ == '__main__':
    main()