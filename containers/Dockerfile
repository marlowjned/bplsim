# bplsim runtime image (Linux). Build from the repository root:
#   docker build -f containers/Dockerfile -t ghcr.io/<org>/bplsim:<tag> .
# On a cluster:  apptainer pull bplsim_<tag>.sif docker://ghcr.io/<org>/bplsim:<tag>
FROM python:3.12-slim

# gmsh's wheel needs a few X/GL libraries even when run headless
RUN apt-get update && apt-get install -y --no-install-recommends \
        libglu1-mesa libxrender1 libxcursor1 libxft2 libxinerama1 libgomp1 wget ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# GetDP: the same version as the legacy Windows build (3.5.0). Binary from getdp.info; check the file name
# on https://getdp.info/bin/Linux/ if the download fails.
ARG GETDP_VERSION=3.5.0
RUN wget -q https://getdp.info/bin/Linux/getdp-${GETDP_VERSION}-Linux64c.tgz \
    && tar xzf getdp-${GETDP_VERSION}-Linux64c.tgz \
    && cp getdp-${GETDP_VERSION}-Linux64/bin/getdp /usr/local/bin/getdp \
    && rm -rf getdp-${GETDP_VERSION}-Linux64*

COPY pyproject.toml README.md /opt/bplsim/
COPY src /opt/bplsim/src
RUN pip install --no-cache-dir /opt/bplsim

ENV OMP_NUM_THREADS=1
ENTRYPOINT ["bplsim"]
