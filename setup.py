import json
import logging
import os
import subprocess
from pathlib import Path

import paramiko
import requests

TOKEN = "secret"
USERNAME = "admin"
SSH_PORT = "29418"
GERRIT_HOST = os.environ.get("GERRIT_HOST", "localhost")
GERRIT_PATH = f"http://{GERRIT_HOST}:8080"
KEY_PATH = Path(__file__).parent / ".ssh"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def generate_ssh_key() -> tuple[Path, Path]:
    """Generates ssh keys if not exist."""
    private_key = KEY_PATH / "id_rsa"
    public_key = KEY_PATH / "id_rsa.pub"

    if private_key.exists() or public_key.exists():
        logger.info("Key pair exist, skipping creation")
        return (private_key, public_key)

    key = paramiko.RSAKey.generate(3072)

    with private_key.open("w") as f:
        key.write_private_key(f)

    with public_key.open("w") as f:
        f.write("ssh-rsa ")
        f.write(key.get_base64())
        f.write(" setup_key")

    private_key.chmod(0o600)

    logger.info("SSH keys generated")
    return (private_key, public_key)


def add_key(key: Path) -> None:
    response = requests.post(
        f"{GERRIT_PATH}/a/accounts/self/sshkeys",
        auth=(USERNAME, TOKEN),
        data=key.read_text(),
    )
    response.raise_for_status()


def gerrit_command(cmd: list[str], private_key: Path) -> str:
    p = subprocess.run(
        [
            "ssh",
            "-o",
            "StrictHostKeyChecking=no",
            "-i",
            private_key.as_posix(),
            "-p",
            SSH_PORT,
            f"{USERNAME}@{GERRIT_HOST}",
            "gerrit",
            *cmd,
        ],
        stdout=subprocess.PIPE,
        check=True,
    )
    return p.stdout.decode()


def ls_repos(key: Path) -> list[str]:
    response = gerrit_command(["ls-projects", "--format=json"], key)
    return json.loads(response).keys()


def create_repo(repo_name: str, key: Path) -> None:
    repos = ls_repos(private)
    if repo_name in repos:
        logger.info(f"Repo '{repo_name}' already exist")
        return

    gerrit_command(["create-project", repo_name], key)


if __name__ == "__main__":
    private, public = generate_ssh_key()
    add_key(public)
    create_repo("zuul-conf", private)
    create_repo("zuul-jobs", private)
