set -euo pipefail -x

cd ui-src
npm ci
npm run build
cp -R dist/* ../noetl/core/ui

cd ../
uv version 1.4.2
uv build