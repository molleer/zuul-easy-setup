FROM ghcr.io/astral-sh/uv:alpine

RUN apk update && apk upgrade && apk add openssh openssl git curl

COPY requirements.txt .
RUN uv venv
RUN . .venv/bin/activate && uv pip install -r requirements.txt

COPY setup.py generate-zk-ca.sh openssl.cnf ./
RUN chmod +x generate-zk-ca.sh

COPY ./repos/ ./repos/

ENV GERRIT_HOST=localhost

CMD [".venv/bin/python", "setup.py"]
