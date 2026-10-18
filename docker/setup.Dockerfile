FROM ghcr.io/astral-sh/uv:alpine

RUN apk update && apk upgrade && apk add openssh openssl git curl

COPY ../src/requirements.txt .
RUN uv venv
RUN . .venv/bin/activate && uv pip install -r requirements.txt

COPY ../src/setup.py ../certs/generate-zk-ca.sh ../certs/openssl.cnf ./
RUN chmod +x generate-zk-ca.sh

COPY ../repos/ ./repos/
COPY ../meta_config/ ./meta_config/

ENV GERRIT_HOST=localhost
ENV CERT_DIRECTORY=./certs
ENV ZUUL_PASSWORD=secret

CMD [".venv/bin/python", "setup.py"]
