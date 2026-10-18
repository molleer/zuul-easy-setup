import json
import logging
import os
import shutil
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory
from time import sleep

import paramiko
import paramiko.pkey
import requests
from jinja2 import Template

ADMIN = "admin"
ADMIN_TOKEN = "secret"
SSH_PORT = "29418"
GERRIT_HOST = os.environ.get("GERRIT_HOST", "localhost")
GERRIT_PATH = f"http://{GERRIT_HOST}:8080"
KEY_PATH = Path(__file__).parent / "ssh"
ZK_CA_SCRIPT = Path(__file__).parent / "generate-zk-ca.sh"
CERT_DIRECTORY = Path(os.environ.get("CERT_DIRECTORY", "./certs"))
ZUUL_PASSWORD = os.environ.get("ZUUL_PASSWORD", "secret")
REPOS = Path(__file__).parent / "repos"
META_CONFIG = Path(__file__).parent / "meta_config"
NODE_POOL_SSH = Path("/nodepool")

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


def add_key(key: Path, user: str, token: str) -> None:
    response = requests.post(
        f"{GERRIT_PATH}/a/accounts/self/sshkeys",
        auth=(user, token),
        data=key.read_text(),
    )
    response.raise_for_status()


def get_groups(user: str, token: str) -> dict[str, str]:
    response = requests.get(
        f"{GERRIT_PATH}/a/groups",
        auth=(user, token),
    )
    response.raise_for_status()
    return {name: info["id"] for name, info in json.loads(response.content.decode().splitlines()[-1]).items()}


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


def _append_to_file(input_file: Path, output_file: Path) -> None:
    output_file.parent.mkdir(exist_ok=True, parents=True)
    output_file.touch(exist_ok=True)

    input_content = input_file.read_text()
    output_content = output_file.read_text()
    if input_content in output_content:
        logger.info(f"{input_file.as_posix()} is already in {output_file.as_posix()}")
        return

    output_file.write_text(f"{output_content}\n{input_content}")


def add_known_hosts(key: Path, directory: Path = KEY_PATH) -> None:
    _append_to_file(key, directory / "known_hosts")


def add_authorized_keys(key: Path, directory: Path = KEY_PATH) -> None:
    _append_to_file(key, directory / "authorized_keys")


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


def _clone_repo(repo: str, cwd: Path, admin_key: Path) -> None:
    repo_dir = cwd / repo

    auth_git_command(
        [
            "clone",
            f"ssh://{ADMIN}@{GERRIT_HOST}:{SSH_PORT}/{repo}",
        ],
        admin_key,
        cwd=cwd,
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


def git_command(cmd: list[str], cwd: Path | None = None) -> str:
    p = subprocess.run(
        ["git", *cmd],
        cwd=cwd.as_posix() if cwd else None,
        stdout=subprocess.PIPE,
        check=True,
    )
    return p.stdout.decode()


def auth_git_command(cmd: list[str], admin_key: Path, cwd: Path | None = None) -> str:
    return git_command(
        ["-c", f"core.sshCommand=ssh -i {admin_key.as_posix()} -o StrictHostKeyChecking=no", *cmd],
        cwd=cwd,
    )


def _git_submit(
    cwd: Path,
    admin_key: Path,
    msg: str = "Add initial files",
    branch: str = "master",
) -> None:
    git_command(["config", "user.email", f"{ADMIN}@example.com"], cwd=cwd)
    git_command(["config", "user.name", ADMIN], cwd=cwd)

    git_command(["add", "-A"], cwd=cwd)
    git_command(["commit", "-m", msg], cwd=cwd)
    auth_git_command(["push", "origin", f"HEAD:refs/for/{branch}"], admin_key, cwd=cwd)
    sha1 = git_command(["rev-parse", "HEAD"], cwd=cwd).strip()

    gerrit_command(["review", sha1, "-l", "Code-Review=2", "-l", "Verified=2", "--submit"], admin_key)


def init_repo(files: Path, admin_key: Path) -> bool:
    if not create_repo(files.name, admin_key):
        return False

    git_command(["config", "--global", "user.email", f"{ADMIN}@example.com"])
    git_command(["config", "--global", "user.name", ADMIN])

    with TemporaryDirectory() as temporary_directory:
        repo_dir = Path(temporary_directory) / files.name
        _clone_repo(files.name, Path(temporary_directory), admin_key)

        for file in files.glob("**/*"):
            if file.is_dir():
                continue

            dst = repo_dir / file.relative_to(files)
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(file.as_posix(), dst)

        _git_submit(repo_dir, admin_key)

    return True


def init_meta_config(repo: str, meta_conifig: Path, admin_key: Path) -> None:
    groups = get_groups(ADMIN, ADMIN_TOKEN)
    context = {f"{name.lower().replace(' ', '_')}_id": group_id for name, group_id in groups.items()}

    with TemporaryDirectory() as temporary_directory:
        repo_dir = Path(temporary_directory) / repo

        _clone_repo(repo, repo_dir.parent, admin_key)
        auth_git_command(["fetch", "origin", "refs/meta/config"], admin_key, cwd=repo_dir)
        git_command(["checkout", "FETCH_HEAD"], cwd=repo_dir)

        for file in meta_conifig.glob("**/*"):
            dest = repo_dir / file.relative_to(meta_conifig).parent / file.name.removesuffix(".j2")

            if file.is_dir():
                continue
            dest.parent.mkdir(exist_ok=True, parents=True)

            if file.name.endswith(".j2"):
                template = Template(file.read_text())
                dest.write_text(template.render(**context))
            else:
                dest.write_text(file.read_text())

        _git_submit(repo_dir, admin_key, "Add initial repo config", "refs/meta/config")


if __name__ == "__main__":
    private, public = generate_ssh_key("admin")
    add_key(public, ADMIN, ADMIN_TOKEN)

    for repo in REPOS.iterdir():
        if init_repo(repo, private):
            init_meta_config(repo.name, META_CONFIG, private)

    try:
        gerrit_command(["create-account", "zuul"], private)
    except subprocess.CalledProcessError:
        pass

    groups = get_groups(ADMIN, ADMIN_TOKEN)
    gerrit_command(["set-members", groups["Service Users"], "--add", "zuul"], private)
    set_password(private, "zuul", ZUUL_PASSWORD)

    z_private, z_public = generate_ssh_key("zuul")
    add_key(z_public, "zuul", ZUUL_PASSWORD)

    _, n_public = generate_ssh_key("nodepool")
    add_known_hosts(n_public, NODE_POOL_SSH)
    add_authorized_keys(n_public, NODE_POOL_SSH)

    generate_zk_certs(CERT_DIRECTORY, "examples_zk_1.examples_default")
