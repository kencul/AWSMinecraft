#!/bin/bash
# Builds the PyNaCl Lambda layer zip file.
# Requires Docker to be running.
# The resulting pynacl-layer.zip is uploaded to AWS Lambda > Layers.

set -e

echo "Building PyNaCl Lambda layer..."

docker run \
  -v "$(pwd)":/var/task \
  "public.ecr.aws/lambda/python:3.13" \
  /bin/sh -c "pip install -r /var/task/layer/requirements.txt -t /var/task/python/; exit"

zip -r layer/pynacl-layer.zip python/
rm -rf python/

echo "Done. Upload layer/pynacl-layer.zip to AWS Lambda > Layers."
echo "Select Python 3.13 as the compatible runtime."
