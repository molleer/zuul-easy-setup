import base64
import json
import logging
import os
import shutil
import subprocess
from pathlib import Path

import paramiko
import paramiko.pkey
import requests

ADMIN = "admin"
SSH_PORT = "29418"
GERRIT_HOST = os.environ.get("GERRIT_HOST", "localhost")
GERRIT_PATH = f"http://{GERRIT_HOST}:8080"
KEY_PATH = Path(__file__).parent / "ssh"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def generate_ssh_key(name: str, directory: Path = KEY_PATH) -> tuple[Path, Path]:
    """Generates ssh keys if not exist."""
    directory.mkdir(exist_ok=True)

    private_key = directory / name
    public_key = directory / f"{name}.pub"

    if private_key.exists() or public_key.exists():
        logger.info(f"Key pair for '{name}' exist, skipping creation")
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


def create_pem(output: Path) -> None:
    if output.exists():
        logger.info(f"'{output.as_posix()}' already exist")
        return

    key = paramiko.RSAKey.generate(3072)
    output.parent.mkdir(parents=True, exist_ok=True)

    with output.open("w") as f:
        key.write_private_key(f, file_format=paramiko.pkey.PEM)


def add_key(key: Path, user: str, token: str | None = None, admin_key: Path | None = None) -> None:
    if not token:
        if not admin_key:
            raise ValueError("Admin key not provided")

        token = gerrit_command(["set-account", user, "--generate-http-password"], admin_key)
        token = token.split(" ")[-1].strip()

    response = requests.post(
        f"{GERRIT_PATH}/a/accounts/self/sshkeys",
        auth=(user, token),
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
            f"{ADMIN}@{GERRIT_HOST}",
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


def create_repo(repo_name: str, key: Path) -> None:
    repos = ls_repos(private)
    if repo_name in repos:
        logger.info(f"Repo '{repo_name}' already exist")
        return

    gerrit_command(["create-project", repo_name], key)


def add_known_hosts(key: Path, directory: Path = KEY_PATH) -> None:
    directory.mkdir(exist_ok=True)
    known_hosts = directory / "known_hosts"

    if not known_hosts.exists():
        known_hosts.touch()

    hosts = known_hosts.read_text()
    key_content = key.read_text()
    if key_content in hosts:
        logger.info(f"{key.name} is already in {known_hosts.as_posix}")
        return

    known_hosts.write_text(f"{hosts}\n{key_content}")


if __name__ == "__main__":
    private, public = generate_ssh_key("admin")
    add_key(public, ADMIN, "secret")
    create_repo("zuul-config", private)
    create_repo("test1", private)
    create_repo("test2", private)

    try:
        gerrit_command(["create-account", "zuul"], private)
    except subprocess.CalledProcessError:
        pass

    z_private, z_public = generate_ssh_key("zuul")
    add_key(z_public, "zuul", admin_key=private)

    _, n_public = generate_ssh_key("nodepool", Path("nodepool"))
    add_known_hosts(n_public)
    create_pem(Path("certs/certs/client.pem"))
    create_pem(Path("certs/keys/clientkey.pem"))
    create_pem(Path("certs/certs/cacert.pem"))
