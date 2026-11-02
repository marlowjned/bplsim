# Containers

`Dockerfile`: a Linux runtime image (Python 3.12, bplsim, GetDP 3.5.0, gmsh's system libraries) for clusters, used
through a site profile's `container:` (Apptainer/Singularity `.sif`). Build from the repository root:

```
docker build -f containers/Dockerfile -t ghcr.io/<org>/bplsim:<tag> .
apptainer pull bplsim_<tag>.sif docker://ghcr.io/<org>/bplsim:<tag>      # on the cluster
```

The image has not been built yet (open issue O3 in `docs/development.md`).
