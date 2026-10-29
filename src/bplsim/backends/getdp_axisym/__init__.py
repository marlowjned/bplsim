"""getdp_axisym: 2-D axisymmetric linear magnetostatics with gmsh + GetDP (plan §7.3).

Port of gmsh_getdp/axisym (geometry.build + axisym.pro). Geometry comes from the parts' r-z regions;
every region becomes its own physical group, so materials and excitations are per region. Each circuit
is solved once at 1 A (superposition). Field access runs GetDP's own post-processing on the stored
solution, so fields are evaluated exactly as GetDP computes them (as the legacy channel grid did).
"""
from __future__ import annotations

import math
import shutil
import subprocess
from pathlib import Path

import numpy as np

from ...errors import BackendError
from ...parts import Param
from ...sites import find_tool
from ...units import mm
from ..base import Backend, Basis, Capabilities, ExecResult, FieldAccess, StageConfig, regions_inputs

HERE = Path(__file__).parent
BND = 9000           # physical tag of the outer boundary
SURF0 = 10000        # first physical tag of named surfaces


def _mu(mat) -> float:
    if not isinstance(mat, dict):
        return 1.0
    p = mat.get("props", {}).get("mu_r_linear")
    if p is None:
        return 1.0
    return float(p["value"] if isinstance(p, dict) else p)


def _getdp() -> str:
    exe = find_tool("getdp")
    if not exe:
        raise BackendError("GetDP not found: set tools.getdp in the site profile, BPLSIM_TOOL_GETDP, or put "
                           "getdp on PATH")
    return exe


class GetDPAxisym(Backend):
    name = "getdp_axisym"
    version = "1.0.0"
    capabilities = Capabilities(dims=2, symmetry="axisymmetric", superposable=True)
    measure_needs_raw = True
    FIDELITY = {
        "nonlinear": Param(False),
        "mesh.h_fine": Param(0.35 * mm, dim="length"),
        "mesh.h_iron": Param(1.2 * mm, dim="length"),
        "mesh.h_far": Param(25 * mm, dim="length"),
        "mesh.fine_r_max": Param(45 * mm, dim="length"),
        "mesh.fine_z_min": Param(-48 * mm, dim="length"),
        "mesh.fine_z_max": Param(30 * mm, dim="length"),
        "mesh.fine_transition": Param(60 * mm, dim="length"),
        "mesh.iron_margin": Param(5 * mm, dim="length"),
        "mesh.iron_transition": Param(80 * mm, dim="length"),
        "air_radius": Param(400 * mm, dim="length"),
        "air_center_z": Param(None, dim="length"),      # None: centre of the parts' z extent
        "timeout": Param(1800.0, dim="time"),
    }

    def tool_version(self) -> str:
        try:
            r = subprocess.run([_getdp(), "--version"], capture_output=True, text=True, timeout=30)
            return (r.stdout or r.stderr).strip().splitlines()[0]
        except (OSError, BackendError, subprocess.SubprocessError, IndexError):
            return ""

    def check(self, design, stage: StageConfig) -> list[str]:
        if stage.fidelity.get("nonlinear"):
            return ["getdp_axisym 1.0 is linear only (nonlinear 2-D is not ported yet)"]
        return []

    def solve_inputs(self, design, stage: StageConfig) -> dict:
        regions, _, circuits = regions_inputs(design, stage, linear=True)
        from ..analytic import _region_dict
        fid = {k: v for k, v in stage.fidelity.items() if k != "timeout"}
        return {"regions": [_region_dict(r) for r in regions], "circuits": circuits, "fidelity": fid}

    # ---- prepare: mesh + regions.pro ----------------------------------------------------------------
    def prepare(self, inputs: dict, workdir: Path) -> None:
        import gmsh
        workdir = Path(workdir)
        f = inputs["fidelity"]
        regs = inputs["regions"]
        gmsh.initialize(["-noenv"])
        try:
            gmsh.option.setNumber("General.Terminal", 0)
            gmsh.model.add("axi")
            occ = gmsh.model.occ
            surf = []
            for r in regs:
                pts = [occ.addPoint(x, y, 0) for x, y in r["points"]]
                lines = [occ.addLine(pts[i], pts[(i + 1) % len(pts)]) for i in range(len(pts))]
                surf.append(occ.addPlaneSurface([occ.addCurveLoop(lines)]))
            zs = [y for r in regs for _, y in r["points"]]
            rs = [x for r in regs for x, _ in r["points"]]
            zc = f.get("air_center_z")
            zc = (min(zs) + max(zs)) / 2 if zc is None else zc
            R = float(f["air_radius"])
            disk = occ.addDisk(0, zc, 0, R, R)
            half = occ.addRectangle(0, zc - R - 1e-3, 0, R + 1e-3, 2 * R + 2e-3)
            air, _ = occ.intersect([(2, disk)], [(2, half)])
            occ.synchronize()
            _, omap = occ.fragment([(2, s) for s in surf] + air, [])
            occ.synchronize()
            owner: dict[int, int] = {}
            for i in range(len(surf)):
                for _, t in omap[i]:
                    if t in owner:
                        raise BackendError(f"regions {owner[t]} and {i} overlap ({regs[owner[t]]['name']}, "
                                           f"{regs[i]['name']})")
                    owner[t] = i
            air_tags = [t for _, t in omap[len(surf)] if t not in owner]
            areas = {}
            for i in range(len(surf)):
                tags = [t for t, o in owner.items() if o == i]
                gmsh.model.addPhysicalGroup(2, tags, i + 1)
                areas[i] = sum(occ.getMass(2, t) for t in tags)
            gmsh.model.addPhysicalGroup(2, air_tags, len(surf) + 1)
            all_tags = list(owner) + air_tags
            bnd = []
            for _, t in gmsh.model.getBoundary([(2, t) for t in all_tags], combined=True, oriented=False):
                xmin, _, _, xmax, _, _ = gmsh.model.getBoundingBox(1, abs(t))
                if xmax > 1e-9:
                    bnd.append(abs(t))
            gmsh.model.addPhysicalGroup(1, bnd, BND)
            # named surfaces -> physical curve groups (curves lying on the named edges)
            curves = [t for _, t in gmsh.model.getEntities(1)]
            cinfo = {}
            for c in curves:
                b = gmsh.model.getBoundary([(1, c)], oriented=False)
                ends = [gmsh.model.getValue(0, abs(p[1]), []) for p in b]
                mid = occ.getCenterOfMass(1, c)
                cinfo[c] = (ends, mid)
            surf_tags = {}
            k = SURF0
            for r in regs:
                for sname, idx in (r.get("surfaces") or {}).items():
                    members = []
                    for i in idx:
                        a, b = r["points"][i], r["points"][(i + 1) % len(r["points"])]
                        for c, (ends, mid) in cinfo.items():
                            if all(_on_segment(e[:2], a, b) for e in ends + [mid]):
                                members.append(c)
                    if members:
                        key = f"{r['name']}.{sname}"
                        gmsh.model.addPhysicalGroup(1, sorted(set(members)), k)
                        surf_tags.setdefault(key, []).append(k)
                        k += 1
            # mesh size fields (legacy layout: fine box over channel and pole gap, medium over the magnet)
            fld = gmsh.model.mesh.field
            box = fld.add("Box")
            fld.setNumber(box, "VIn", f["mesh.h_fine"])
            fld.setNumber(box, "VOut", f["mesh.h_far"])
            fld.setNumber(box, "XMin", 0.0)
            fld.setNumber(box, "XMax", f["mesh.fine_r_max"])
            fld.setNumber(box, "YMin", f["mesh.fine_z_min"])
            fld.setNumber(box, "YMax", f["mesh.fine_z_max"])
            fld.setNumber(box, "Thickness", f["mesh.fine_transition"])
            box2 = fld.add("Box")
            m = f["mesh.iron_margin"]
            fld.setNumber(box2, "VIn", f["mesh.h_iron"])
            fld.setNumber(box2, "VOut", f["mesh.h_far"])
            fld.setNumber(box2, "XMin", 0.0)
            fld.setNumber(box2, "XMax", max(rs) + m)
            fld.setNumber(box2, "YMin", min(zs) - m)
            fld.setNumber(box2, "YMax", max(zs) + 8 * m)
            fld.setNumber(box2, "Thickness", f["mesh.iron_transition"])
            mn = fld.add("Min")
            fld.setNumbers(mn, "FieldsList", [box, box2])
            fld.setAsBackgroundMesh(mn)
            gmsh.option.setNumber("Mesh.MeshSizeFromPoints", 0)
            gmsh.option.setNumber("Mesh.MeshSizeExtendFromBoundary", 0)
            gmsh.option.setNumber("Mesh.MeshSizeFromCurvature", 0)
            gmsh.model.mesh.generate(2)
            gmsh.write(str(workdir / "axi.msh"))
            n_elem = int(sum(len(e) for e in gmsh.model.mesh.getElements(2)[1]))
        finally:
            gmsh.finalize()
        # regions.pro
        lines = ["// generated by bplsim getdp_axisym", "Group {"]
        mag, wind, plain = [], [], []
        for i, r in enumerate(regs):
            lines.append(f"  R{i} = Region[{i + 1}];  // {r['name']}")
            (wind if r.get("excitation") else (mag if _mu(r["material"]) != 1.0 else plain)).append(f"R{i}")
        lines.append(f"  Air = Region[{{{len(regs) + 1}{', ' + ', '.join(plain) if plain else ''}}}];")
        lines.append(f"  Mag = Region[{{{', '.join(mag)}}}];")
        lines.append(f"  Windings = Region[{{{', '.join(wind)}}}];")
        lines.append("  Domain = Region[{Air, Mag, Windings}];")
        lines.append(f"  Bnd = Region[{BND}];")
        for key, tags in surf_tags.items():
            lines.append(f"  S_{_ident(key)} = Region[{{{', '.join(map(str, tags))}}}];")
        lines.append("}")
        consts = ", ".join(f"I_{_ident(c)} = 0" for c in inputs["circuits"]) or "I_none = 0"
        lines.append(f"DefineConstant[ {consts} ];")
        lines.append("mu0 = 4e-7 * Pi;")
        lines.append("Function {")
        lines.append("  nu[Region[{Air, Windings}]] = 1 / mu0;")
        for i, r in enumerate(regs):
            if f"R{i}" in mag:
                lines.append(f"  nu[R{i}] = 1 / (mu0 * {_mu(r['material'])!r});")
        for i, r in enumerate(regs):
            exc = r.get("excitation")
            if exc:
                # J_theta = sign * turns * I / area; gmsh's out-of-plane axis is -theta for x = r, y = z
                coef = -exc.get("sign", 1) * exc["turns"] / areas[i]
                lines.append(f"  js[R{i}] = Vector[0, 0, {coef!r} * I_{_ident(exc['circuit'])}];")
        lines.append("}")
        (workdir / "regions.pro").write_text("\n".join(lines) + "\n")
        shutil.copy(HERE / "axi.pro", workdir / "axi.pro")
        (workdir / "post.pro").write_text("// replaced per query\n")
        (workdir / "mesh_info.txt").write_text(f"elements {n_elem}\n")

    # ---- execute -------------------------------------------------------------------------------------
    def execute(self, inputs: dict, workdir: Path, basis: Basis, resources: dict) -> ExecResult:
        workdir = Path(workdir)
        cmd = [_getdp(), "axi.pro", "-msh", "axi.msh", "-solve", "Res", "-v", "2"]
        for c, i in basis.currents.items():
            cmd += ["-setnumber", f"I_{_ident(c)}", repr(float(i))]
        timeout = float(resources.get("timeout") or inputs.get("fidelity", {}).get("timeout") or 1800)
        try:
            r = subprocess.run(cmd, cwd=workdir, capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            return ExecResult("failed", f"getdp timed out after {timeout:.0f} s")
        if r.returncode != 0 or not (workdir / "axi.res").exists():
            return ExecResult("failed", f"getdp failed: {(r.stdout + r.stderr)[-1500:]}")
        (workdir / "axi.res").replace(workdir / f"basis_{basis.name}.res")
        return ExecResult()

    def field_access(self, inputs: dict, workdir: Path, basis: Basis) -> FieldAccess:
        return GetDPField(Path(workdir), basis, inputs)


def _ident(s: str) -> str:
    return "".join(ch if ch.isalnum() else "_" for ch in s)


def _on_segment(p, a, b, tol=1e-9) -> bool:
    (px, py), (ax, ay), (bx, by) = p, a, b
    L = math.hypot(bx - ax, by - ay)
    if L == 0:
        return math.hypot(px - ax, py - ay) < tol
    cross = abs((bx - ax) * (py - ay) - (by - ay) * (px - ax)) / L
    dot = ((px - ax) * (bx - ax) + (py - ay) * (by - ay)) / L
    return cross < tol and -tol <= dot <= L + tol


def _fmt(vals) -> str:
    return ", ".join(repr(float(v)) for v in vals)


class GetDPField(FieldAccess):
    symmetry = "axisymmetric"

    def __init__(self, workdir: Path, basis: Basis, inputs: dict):
        self.dir, self.basis, self.inputs = workdir, basis, inputs
        self.res = workdir / f"basis_{basis.name}.res"
        if not self.res.exists():
            raise BackendError(f"no solution for basis {basis.name} in {workdir} (raw output purged?)")
        self._n = 0

    def _post(self, body: str) -> Path:
        self._n += 1
        out = f"q{self._n}.txt"
        (self.dir / "post.pro").write_text(
            "PostOperation {\n  { Name Q; NameOfPostProcessing PP;\n    Operation {\n" +
            body.replace("@OUT@", out) + "\n    }\n  }\n}\n")
        cmd = [_getdp(), "axi.pro", "-msh", "axi.msh", "-res", self.res.name, "-pos", "Q", "-v", "2"]
        r = subprocess.run(cmd, cwd=self.dir, capture_output=True, text=True, timeout=3600)
        path = self.dir / out
        if r.returncode != 0 or not path.exists():
            raise BackendError(f"getdp post-processing failed: {(r.stdout + r.stderr)[-1500:]}")
        return path

    @staticmethod
    def _table(path: Path) -> np.ndarray:
        a = np.loadtxt(path, ndmin=2)
        path.unlink()
        return a

    def _elements(self, tags: list[int] | None = None) -> np.ndarray:
        """Per-element node coordinates and nodal B (GetDP Depth 1): rows of 18 values, cached on disk."""
        key = "all" if tags is None else "_".join(map(str, tags))
        cache = self.dir / f"elem_{self.basis.name}_{key}.npy"
        if cache.exists():
            return np.load(cache)
        where = "Domain" if tags is None else f"Region[{{{', '.join(map(str, tags))}}}]"
        body = f'      Print[ b, OnElementsOf {where}, Depth 1, File "@OUT@", Format SimpleTable ];'
        path = self._post(body)
        import pandas as pd
        a = pd.read_csv(path, sep=r"\s+", header=None).to_numpy(float)
        path.unlink()
        np.save(cache, a)
        return a

    def _interp(self, r: np.ndarray, z: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Locate each point in its triangle and interpolate GetDP's nodal B (linear within an element)."""
        from scipy.spatial import cKDTree
        e = self._elements()
        P = e[:, [0, 1, 3, 4, 6, 7]].reshape(-1, 3, 2)
        B = e[:, [9, 10, 12, 13, 15, 16]].reshape(-1, 3, 2)
        tree = cKDTree(P.mean(axis=1))
        pts = np.column_stack([r, z])
        k = 12
        _, cand = tree.query(pts, k=k)
        a0, a1, a2 = P[cand, 0], P[cand, 1], P[cand, 2]                 # (n, k, 2)
        v0, v1, v2 = a1 - a0, a2 - a0, pts[:, None, :] - a0
        d00 = (v0 * v0).sum(-1); d01 = (v0 * v1).sum(-1); d11 = (v1 * v1).sum(-1)
        d20 = (v2 * v0).sum(-1); d21 = (v2 * v1).sum(-1)
        den = d00 * d11 - d01 * d01
        l1 = (d11 * d20 - d01 * d21) / den
        l2 = (d00 * d21 - d01 * d20) / den
        l0 = 1 - l1 - l2
        lam = np.stack([l0, l1, l2], axis=-1)                          # (n, k, 3)
        inside = np.all(lam >= -1e-9, axis=-1)
        if not np.all(inside.any(axis=1)):
            bad = np.flatnonzero(~inside.any(axis=1))
            raise BackendError(f"{len(bad)} sample point(s) outside the mesh, e.g. r={r[bad[0]]:.6g}, z={z[bad[0]]:.6g}")
        # value in every containing element; a point on an element edge (where first-order B is
        # discontinuous) gets the mean of the elements that share it
        vals = (np.clip(lam, 0, None)[..., None] * B[cand]).sum(axis=2)  # (n, k, 2)
        w = inside.astype(float)
        b = (vals * w[..., None]).sum(axis=1) / w.sum(axis=1)[:, None]
        return b[:, 0], b[:, 1]

    def _eval_rz(self, r: np.ndarray, z: np.ndarray, exact: bool = False) -> tuple[np.ndarray, np.ndarray]:
        """B_r, B_z at points (r, z). Default: interpolate GetDP's element-nodal B (fast). exact=True:
        GetDP evaluates every point itself (OnGrid / OnPoint; slow, used to validate the fast path)."""
        if not exact:
            return self._interp(np.asarray(r, float), np.asarray(z, float))
        ur, uz = np.unique(np.round(r, 12)), np.unique(np.round(z, 12))
        if len(ur) * len(uz) <= 4 * len(r):
            body = (f"      Print[ b, OnGrid {{$A, $B, 0}} {{ {{{_fmt(ur)}}}, {{{_fmt(uz)}}}, {{0}} }}, "
                    f'File "@OUT@", Format SimpleTable ];')
            a = self._table(self._post(body))
            from scipy.spatial import cKDTree
            d, idx = cKDTree(a[:, 0:2]).query(np.column_stack([r, z]))
            if np.max(d) > 1e-9:
                raise BackendError("GetDP grid output does not match the requested points")
            return a[idx, 3], a[idx, 4]
        body = "\n".join(f'      Print[ b, OnPoint {{{x!r}, {y!r}, 0}}, File >> "@OUT@", Format SimpleTable ];'
                         for x, y in zip(r.tolist(), z.tolist()))
        a = self._table(self._post(body))
        return a[:, -3], a[:, -2]

    def sample(self, where, fields=("B",)):
        from ...measure.data import ProbeData
        ru, zu, inv = where.rz_unique()
        br, bz = self._eval_rz(ru, zu)
        shape = where.shape
        return ProbeData({"r": where.r, "theta": where.theta, "z": where.z},
                         {"B_r": br[inv].reshape(shape), "B_theta": np.zeros(shape), "B_z": bz[inv].reshape(shape)},
                         {"symmetry": "axisymmetric"}, where.axes)

    def _groups_of(self, slot: str) -> list[int]:
        return [i + 1 for i, r in enumerate(self.inputs["regions"]) if r["name"] == slot]

    def region(self, part: str, fields=("B",)):
        from ...measure.data import ProbeData
        tags = self._groups_of(part)
        if not tags:
            raise BackendError(f"no region for part {part!r}")
        e = self._elements(tags)
        P = e[:, [0, 1, 3, 4, 6, 7]].reshape(-1, 3, 2)
        B = e[:, [9, 10, 12, 13, 15, 16]].reshape(-1, 3, 2)
        c = P.mean(axis=1)
        area = 0.5 * np.abs((P[:, 1, 0] - P[:, 0, 0]) * (P[:, 2, 1] - P[:, 0, 1]) -
                            (P[:, 2, 0] - P[:, 0, 0]) * (P[:, 1, 1] - P[:, 0, 1]))
        b = B.mean(axis=1)                                   # centroid value of a linear field
        r, z = c[:, 0], c[:, 1]
        return ProbeData({"r": r, "theta": np.zeros_like(r), "z": z, "weight": 2 * math.pi * r * area},
                         {"B_r": b[:, 0], "B_theta": np.zeros_like(r), "B_z": b[:, 1]}, {"symmetry": "axisymmetric"})

    def boundary(self, surface: str, fields=("B",)):
        """B just outside a named surface: one point per mesh segment, offset 1 um along the outward normal."""
        from ...measure.data import ProbeData
        from shapely.geometry import Point, Polygon
        slot, name = surface.split(".", 1)
        segs = []
        for reg in self.inputs["regions"]:
            if reg["name"] != slot or name not in (reg.get("surfaces") or {}):
                continue
            poly = Polygon(reg["points"])
            for (a, b) in _mesh_segments(self.dir / "axi.msh", reg, name):
                segs.append((a, b, poly))
        if not segs:
            raise BackendError(f"no surface {surface!r}")
        rs, zs, nr_, nz_, ws = [], [], [], [], []
        for (ra, za), (rb, zb), poly in segs:
            L = math.hypot(rb - ra, zb - za)
            nr, nz = (zb - za) / L, -(rb - ra) / L
            mr, mz = (ra + rb) / 2, (za + zb) / 2
            if poly.contains(Point(mr + 1e-7 * nr, mz + 1e-7 * nz)):
                nr, nz = -nr, -nz
            rs.append(mr + 1e-6 * nr)
            zs.append(mz + 1e-6 * nz)
            nr_.append(nr)
            nz_.append(nz)
            ws.append(2 * math.pi * mr * L)
        r, z = np.array(rs), np.array(zs)
        br, bz = self._eval_rz(r, z)
        return ProbeData({"r": r, "theta": np.zeros_like(r), "z": z, "n_r": np.array(nr_), "n_z": np.array(nz_),
                          "weight": np.array(ws)},
                         {"B_r": br, "B_theta": np.zeros_like(r), "B_z": bz}, {"symmetry": "axisymmetric"})

    def export_grid(self, grid, fields=("B",), fmt="npz", path=None):
        r = np.arange(grid["r"][0], grid["r"][1] + 1e-12, grid["spacing"])
        z = np.arange(grid["z"][0], grid["z"][1] + 1e-12, grid["spacing"])
        R, Z = np.meshgrid(r, z, indexing="ij")
        br, bz = self._eval_rz(R.ravel(), Z.ravel())
        np.savez(path, r=r, z=z, B_r=br.reshape(R.shape), B_z=bz.reshape(R.shape))
        return path


def _element_centroids_areas(msh: Path, phys_tags: list[int]):
    import gmsh
    gmsh.initialize(["-noenv"])
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.open(str(msh))
        cen, area = [], []
        for pt in phys_tags:
            for ent in gmsh.model.getEntitiesForPhysicalGroup(2, pt):
                types, tags, nodes = gmsh.model.mesh.getElements(2, ent)
                for et, nt in zip(types, nodes):
                    n_per = gmsh.model.mesh.getElementProperties(et)[3]
                    nt = np.asarray(nt).reshape(-1, n_per)[:, :3]
                    coords = {}
                    uniq = np.unique(nt)
                    for n in uniq:
                        coords[int(n)] = gmsh.model.mesh.getNode(int(n))[0][:2]
                    p = np.array([[coords[int(n)] for n in tri] for tri in nt])
                    c = p.mean(axis=1)
                    a = 0.5 * np.abs((p[:, 1, 0] - p[:, 0, 0]) * (p[:, 2, 1] - p[:, 0, 1]) -
                                     (p[:, 2, 0] - p[:, 0, 0]) * (p[:, 1, 1] - p[:, 0, 1]))
                    cen.append(c)
                    area.append(a)
        return np.vstack(cen), np.concatenate(area)
    finally:
        gmsh.finalize()


def _mesh_segments(msh: Path, reg: dict, surface: str):
    """Mesh line segments (pairs of (r, z)) lying on a region's named edges."""
    import gmsh
    pts = reg["points"]
    edges = [(pts[i], pts[(i + 1) % len(pts)]) for i in reg["surfaces"][surface]]
    gmsh.initialize(["-noenv"])
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.open(str(msh))
        out = []
        for _, c in gmsh.model.getEntities(1):
            types, tags, nodes = gmsh.model.mesh.getElements(1, c)
            for et, nt in zip(types, nodes):
                nt = np.asarray(nt).reshape(-1, 2)
                for a, b in nt:
                    pa = gmsh.model.mesh.getNode(int(a))[0][:2]
                    pb = gmsh.model.mesh.getNode(int(b))[0][:2]
                    for ea, eb in edges:
                        if _on_segment(pa, ea, eb) and _on_segment(pb, ea, eb):
                            out.append((tuple(pa), tuple(pb)))
                            break
        return out
    finally:
        gmsh.finalize()
