import json
import logging
import os
import shutil
import subprocess
from pathlib import Path

import paramiko
import paramiko.pkey
import requests
from tempfile import TemporaryDirectory

ADMIN = "admin"
SSH_PORT = "29418"
GERRIT_HOST = os.environ.get("GERRIT_HOST", "localhost")
GERRIT_PATH = f"http://{GERRIT_HOST}:8080"
KEY_PATH = Path(__file__).parent / "ssh"
ZK_CA_SCRIPT = Path(__file__).parent / "generate-zk-ca.sh"
CERT_DIRECTORY = Path(os.environ.get("CERT_DIRECTORY", "./certs"))
ZUUL_PASSWORD = os.environ.get("ZUUL_PASSWORD", "secret")
REPOS = Path(__file__).parent / "repos"

COMMIT_COUNT = 0

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


def set_password(admin_key: Path, user: str, password: str) -> None:
    gerrit_command(["set-account", user, "--http-password", password], admin_key)


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
        return False

    gerrit_command(["create-project", repo_name, "--branch", "master", "--empty-commit"], key)
    return True


def add_known_hosts(key: Path, directory: Path = KEY_PATH) -> None:
    directory.mkdir(exist_ok=True)
    known_hosts = directory / "known_hosts"

    if not known_hosts.exists():
        known_hosts.touch()

    hosts = known_hosts.read_text()
    key_content = key.read_text()
    if key_content in hosts:
        logger.info(f"{key.name} is already in {known_hosts.as_posix()}")
        return

    known_hosts.write_text(f"{hosts}\n{key_content}")


def generate_zk_certs(output: Path, name: str) -> None:
    output.mkdir(parents=True, exist_ok=True)

    p = subprocess.run(
        [
            ZK_CA_SCRIPT.resolve().absolute().as_posix(),
            output.as_posix(),
            name,
        ],
        stdout=subprocess.PIPE,
        check=True,
    )
    logger.info(p.stdout.decode())

    subprocess.run(["chmod", "-R", "a+rX", output.as_posix()], check=True)


def init_repo(files: Path, admin_key=Path) -> None:
    global COMMIT_COUNT

    if not create_repo(files.name, admin_key):
        return

    with TemporaryDirectory() as temporary_directory:
        repo_dir = Path(temporary_directory) / files.name

        subprocess.run(
            [
                "git",
                "clone",
                "-c",
                f"core.sshCommand=ssh -i {admin_key.as_posix()} -o StrictHostKeyChecking=no",
                f"ssh://{ADMIN}@{GERRIT_HOST}:{SSH_PORT}/{files.name}",
            ],
            cwd=temporary_directory,
            check=True,
        )
        (repo_dir / ".git/hooks").mkdir(parents=True, exist_ok=True)
        subprocess.run(
            [
                "curl",
                "-fLo",
                f"{repo_dir.as_posix()}/.git/hooks/commit-msg",
                f"http://{GERRIT_HOST}:8080/tools/hooks/commit-msg",
            ],
            cwd=repo_dir.as_posix(),
        )
        (repo_dir / ".git/hooks/commit-msg").chmod(0o755)

        for file in files.glob("**/*"):
            if file.is_dir():
                continue

            dst = repo_dir / file.relative_to(files)
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(file.as_posix(), dst)

        subprocess.run(["git", "config", "--global", "user.email", f"{ADMIN}@example.com"], check=True)
        subprocess.run(["git", "config", "--global", "user.name", ADMIN], check=True)
        subprocess.run(["git", "add", "-A"], cwd=repo_dir.as_posix(), check=True)
        subprocess.run(["git", "commit", "-m", "Add initial files"], cwd=repo_dir.as_posix(), check=True)
        subprocess.run(["git", "push", "origin", "HEAD:refs/for/master"], cwd=repo_dir.as_posix(), check=True)
        COMMIT_COUNT += 1

        gerrit_command(["review", f"{COMMIT_COUNT},1", "-l", "Code-Review=2", "--submit"], admin_key)


if __name__ == "__main__":
    private, public = generate_ssh_key("admin")
    add_key(public, ADMIN, "secret")

    for repo in REPOS.iterdir():
        init_repo(repo, private)

    try:
        gerrit_command(["create-account", "zuul"], private)
        set_password(private, "zuul", ZUUL_PASSWORD)
        # TODO: Add zuul user to Service Users
    except subprocess.CalledProcessError:
        pass

    z_private, z_public = generate_ssh_key("zuul")
    add_key(z_public, "zuul", admin_key=private)

    _, n_public = generate_ssh_key("nodepool", Path("nodepool"))
    add_known_hosts(n_public)

    generate_zk_certs(CERT_DIRECTORY, "examples_zk_1.examples_default")
