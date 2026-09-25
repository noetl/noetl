set -euo pipefail -x

# The embedded UI was removed from this repo in e06ed7d2 and now lives in
# https://github.com/noetl/gui ; the copy target noetl/core/ui/ went with the
# Python platform in 25bef859.  Nothing to build here any more.
uv version 1.4.2
uv build