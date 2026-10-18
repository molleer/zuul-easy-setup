# Mirror of docker.io/library/ubuntu:22.04
FROM quay.io/opendevmirror/ubuntu:22.04

RUN apt-get update \
    && DEBIAN_FRONTEND="noninteractive" apt-get -y install \
    git \
    openssh-server \
    rsync \
    && rm -rf /var/lib/apt/lists/*

# If proxy environment variables supplied during build allow pass through via
# ~/.ssh/environment, as the test env likely will require these set for any
# job launched on the node to be capable of internet access.
RUN set -e ; \
    mkdir /var/run/sshd ; \
    mkdir -p -m 0700 ~/.ssh; \
    if [ -n "${http_proxy}" ]; then \
    sed -ri 's/#PermitUserEnvironment no/PermitUserEnvironment yes/g' /etc/ssh/sshd_config; \
    echo "http_proxy=${http_proxy}" > ~/.ssh/environment; \
    echo "https_proxy=${https_proxy}" >> ~/.ssh/environment; \
    echo "no_proxy=${no_proxy}" >> ~/.ssh/environment; \
    fi \
    ;

COPY --chown=root:root ./ssh_host_ed25519_key /etc/ssh/ssh_host_ed25519_key
COPY --chown=root:root ./ssh_host_ed25519_key.pub /etc/ssh/ssh_host_ed25519_key.pub
RUN chmod 0600 /etc/ssh/ssh_host_ed25519_key
RUN chmod 0644 /etc/ssh/ssh_host_ed25519_key.pub

EXPOSE 22

ENTRYPOINT ["/usr/sbin/sshd", "-D" ]
