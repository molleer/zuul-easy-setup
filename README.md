# Zuul Easy Setup

Setting up gerrit and zuul in a local environment takes quite
a long time to do manually since there are many steps to take
and mistakes are easily made. This repo aims to make the
experience better by allowing you to set up your own environment
in docker.

## Setup Gerrit and Zuul

```
docker compose up -d
```

And that's it!

**WARNING**: Do not use the configuration in production as is. Password are and
other configurations my be insecure and should be updated accordingly before
being used in production.

## Source material

The configuration mainly follows the [Quick-Start Installation and
Tutorial](https://zuul-ci.org/docs/zuul/latest/tutorials/quick-start.html).
Any manual steps in the tutorial has been automated in the `src/setup.py`
script which runs on startup.

## Services

After the `docker compose` command has been executed as above, the
following services will be available and configured.

- [Gerrit Code Review](https://www.gerritcodereview.com/): http://localhost:8080
    - A running gerrit instance
    - Repos:
        - `zuul-conf`: Trusted zuul config repository
        - `test1`: Untrusted git repository
    - Creating a new change to `test1` will start a `check` pipeline in Zuul
    - Once `check` has passed and the change is given `Code-Review` +2,
    the `gate` pipeline will start
    - Once `gate` has passed, the change will be submitted automatically
- [Zuul Web Server](https://zuul-ci.org/docs/zuul/latest/configuration.html#web-server): http://localhost:9000
    - This page visualizes all Zuul jobs, projects, pipelines etc.
- [Zuul executor](https://zuul-ci.org/docs/zuul/latest/configuration.html#executor)
- [Zuul scheduler](https://zuul-ci.org/docs/zuul/latest/configuration.html#scheduler)
- [Zuul launcher](https://zuul-ci.org/docs/zuul/latest/configuration.html#launcher)
- [Zookeeper](https://zuul-ci.org/docs/zuul/latest/developer/zookeeper.html#zookeeper)
- node
    - A static node/worker which is used by default to run playbooks in zuul jobs
- logs
    - Http server to store log files
- mysql
    - A MariaDB server

## `src/setup.py`

These are the configuration steps done by the setup `src/script.py`

1. Generates ssh key pair for admin user and adds it to gerrit
2. Copies the content of `repos` into each respective gerrit repo
3. Copies the content of `meta_config` into `refs/meta/config` of each repo
4. Creates a `zuul` user in gerrit
5. Adds `zuul` to the `Service Users` group (required for zuul to stream gerrit events)
6. Generates ssk key pairs and sets password for the `zuul` user in gerrit
7. Generates ssh key pair for the zuul executor (used by the zuul executor to communicate with the given node)
8. Adds the zuul executor key to the `known_hosts` and `authorized_keys` in the static node
9. Generates Zookeeper certificates (used to enable secure communication between all Zuul microservices)
