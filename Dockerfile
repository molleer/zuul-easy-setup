FROM ghcr.io/astral-sh/uv:alpine

RUN apk update && apk upgrade && apk add openssh

COPY requirements.txt .
RUN uv venv
RUN . .venv/bin/activate && uv pip install -r requirements.txt

COPY setup.py .

ENV GERRIT_HOST=localhost

CMD [".venv/bin/python", "setup.py"]
