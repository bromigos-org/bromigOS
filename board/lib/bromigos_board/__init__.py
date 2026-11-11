"""The Lab board's server side (docs/board.md): bromigOS Server's own web page.

  paths     where everything lives, under a stand-in root for tests (BROMIGOS_ROOT)
  net       which source addresses may reach the page: private ones only
  auth      the one-time console code, sessions and CSRF tokens
  door      what the page shows before sign-in: app tiles, from an allow-list
  snapshot  the root-run reader that writes /run/bromigos-board/board.json
  api       the Starlette app on the service's Unix socket
  cli       bromigos-board's commands (code, sessions, snapshot, serve)
"""

SCHEMA = 1
