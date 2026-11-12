#!/usr/bin/env bash
# Linux/macOS counterpart of start.ps1 -Https. Usage: ./start.sh [--http] [--skip-contest-import]
#   --http                 plain HTTP only (like start.ps1 without -Https)
#   --skip-contest-import  do not load the bundled official v1.1.0 sample data
# Requires Docker with Compose v2; HTTPS also needs openssl (1.1.1+ for -addext) to create the local CA once.
set -euo pipefail
cd "$(dirname "$0")"
https=1
import=1
for arg in "$@"; do
  case "$arg" in
    --http) https=0 ;;
    --skip-contest-import) import=0 ;;
    *) echo "Unknown option: $arg" >&2; exit 2 ;;
  esac
done

token() { od -An -tx1 -N16 /dev/urandom | tr -d ' \n'; }

if [ ! -f .env ]; then
  (umask 077
   for setting in DB_PASSWORD AGENT_TOKEN ALPHA_PASSWORD BETA_PASSWORD; do
     echo "PRODUCT_${setting}=$(token)"
   done > .env)
fi
for setting in IMPORT_TOKEN S3_PASSWORD; do
  grep -q "^PRODUCT_${setting}=" .env || echo "PRODUCT_${setting}=$(token)" >> .env
done
for setting in MODEL_BASE_URL MODEL_NAME MODEL_API_KEY; do
  grep -q "^PRODUCT_${setting}=" .env || echo "PRODUCT_${setting}=" >> .env
done
echo 'Chat needs PRODUCT_MODEL_BASE_URL and PRODUCT_MODEL_NAME in product/.env.'

files=(-f compose.yaml)
if [ "$https" = 1 ]; then
  # Same certificates as tls/generate-local.ps1: local CA (365 days) + localhost server cert (90 days).
  (
    mkdir -p tls/local && cd tls/local
    present=0
    for f in ca.crt ca.key server.crt server.key; do [ -f "$f" ] && present=$((present + 1)); done
    if [ "$present" -ne 4 ]; then
      if [ "$present" -gt 0 ]; then echo 'Local TLS directory is incomplete. Move it aside before regenerating.' >&2; exit 1; fi
      printf '[req]\ndistinguished_name = dn\n[dn]\n' > req.cnf
      openssl req -config req.cnf -x509 -newkey rsa:2048 -nodes -sha256 -days 365 -subj '/CN=Tax Product Local CA' \
        -addext 'basicConstraints=critical,CA:TRUE' -addext 'keyUsage=critical,keyCertSign,cRLSign' -keyout ca.key -out ca.crt
      openssl req -config req.cnf -new -newkey rsa:2048 -nodes -subj '/CN=localhost' -keyout server.key -out server.csr
      printf 'basicConstraints=critical,CA:FALSE\nkeyUsage=critical,digitalSignature,keyEncipherment\nextendedKeyUsage=serverAuth\nsubjectAltName=DNS:localhost,IP:127.0.0.1\n' > server.ext
      openssl x509 -req -in server.csr -CA ca.crt -CAkey ca.key -CAcreateserial -out server.crt -days 90 -sha256 -extfile server.ext
    fi
  )
  files+=(-f compose.https.yaml)
fi

docker compose "${files[@]}" up --build --remove-orphans --wait --wait-timeout 120 \
  || { echo 'Product startup failed. Check the Compose output.' >&2; exit 1; }

if [ "$import" = 1 ]; then
  # Official v1.1.0 sample data (product/data/contest), imported inside the importer image: only Docker is needed.
  # Check first; import only missing rows (never overwrites edited purpose/note), then check again.
  importer=(docker compose "${files[@]}" run --rm --no-deps -T --user "$(id -u):$(id -g)" -v "$PWD:/work"
            --entrypoint python importer /work/import_contest_data.py --direct-db --allow-main)
  if ! "${importer[@]}" --check-only; then
    echo 'Contest data missing or incomplete, importing...'
    "${importer[@]}" || { echo 'Contest data import failed. See the importer output above.' >&2; exit 1; }
    "${importer[@]}" --check-only || { echo 'Contest data check failed after import. See the importer output above.' >&2; exit 1; }
  fi
  echo '赛题数据就绪：40 张发票、48 条流水'
fi
