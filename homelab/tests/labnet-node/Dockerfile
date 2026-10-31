# A lab machine for e2e_labnet.py: systemd, Podman (for the Quadlet), SSH and passwordless sudo.
# Built and run only by the test, privileged, on its own Docker network.
FROM docker.io/library/fedora:42
RUN dnf -y install --setopt=install_weak_deps=False podman openssh-server sudo python3 systemd procps-ng iproute && dnf clean all
RUN useradd -m lab && echo 'lab ALL=(ALL) NOPASSWD: ALL' > /etc/sudoers.d/lab && chmod 0440 /etc/sudoers.d/lab \
 && mkdir -p /home/lab/.ssh && chmod 700 /home/lab/.ssh && chown lab:lab /home/lab/.ssh \
 && systemctl enable sshd && ssh-keygen -A \
 && printf '[storage]\ndriver = "vfs"\n' > /etc/containers/storage.conf
STOPSIGNAL SIGRTMIN+3
CMD ["/sbin/init"]
