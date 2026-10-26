# The public image of BRODEC's lab bridge, ghcr.io/bromigos-org/brodec-lab. Built by
# .github/workflows/brodec-lab.yml from the binary that packaging/ci/brodec-lab.sh fetched and
# checked; the build context holds that binary as brodec-lab. Nothing is compiled here.
#
# Runs as user 10001 with a read-only root filesystem: it writes only to /data (its volume)
# and /tmp. ffmpeg reads voice messages and pdftotext reads PDFs sent to VECTOR.
FROM debian:trixie-slim@sha256:62bd423aeee912639ca8ee681c2b762cb3e25137e0a92b20be455898a9f034ad
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates ffmpeg poppler-utils \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --system --uid 10001 --user-group --home-dir /data --no-create-home brodec-lab \
    && install -d -o 10001 -g 10001 -m 0700 /data
COPY --chmod=0755 brodec-lab /usr/local/bin/brodec-lab
ENV BRODEC_DATA_DIR=/data
USER 10001:10001
VOLUME ["/data"]
ENTRYPOINT ["/usr/local/bin/brodec-lab"]
CMD ["run"]
