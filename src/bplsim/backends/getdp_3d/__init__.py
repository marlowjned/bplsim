"""getdp_3d: 3-D magnetostatics with gmsh + GetDP (plan §7.4), the formulation of the legacy
gmsh_getdp/assembly pipeline, with geometry from the parts' `solid_3d` recipes instead of CAD imports.

Linear iron is superposable (one solve per circuit at 1 A); nonlinear iron uses each material's B-H curve
(nu(|b|^2) interpolation of a monotone resampling of the table, see nu_table; current ramp; Newton or Picard)
and one solve with the actual currents.
Field access interpolates GetDP's element-nodal B inside each tetrahedron (as getdp_axisym does in 2-D).
"""
from __future__ import annotations

import math
import shutil
import subprocess
from pathlib import Path

import numpy as np

from ...errors import BackendError
from ...geom.cad import Solid, realise
from ...parts import Param
from ...units import mm
from ..base import Backend, Basis, Capabilities, ExecResult, FieldAccess, StageConfig
from ..getdp_axisym import _getdp, _ident

HERE = Path(__file__).parent
BND = 9000
MU0 = 4e-7 * math.pi


def nu_table(H, B, n: int = 160, check: str = "akima") -> tuple[np.ndarray, np.ndarray]:
    """Reluctivity table (B^2, nu) for GetDP's nu(|b|^2) interpolation, from a B-H table.

    H(B) is interpolated with a monotone cubic (PCHIP) on the table itself and resampled at n points (uniform in
    B up to the last table point), so the table's own shape is kept (including the low-field S-shape of real
    steel) while the interpolant GetDP builds on top stays monotone. Interpolating nu = H/B at the table points
    only, as before, made H(B) decrease between table points for coarse tables (het a36: 0.65-0.80 T), which
    is unphysical and stalls Newton. Raises BackendError if the table is not strictly increasing or if the
    interpolated H(B) (Akima or linear in B^2, as GetDP will use it) is not increasing."""
    from scipy.interpolate import Akima1DInterpolator, PchipInterpolator
    H, B = np.asarray(H, float), np.asarray(B, float)
    if B[0] > 0:
        H, B = np.concatenate([[0.0], H]), np.concatenate([[0.0], B])
    if np.any(np.diff(B) <= 0) or np.any(np.diff(H) <= 0):
        raise BackendError("B-H table must be strictly increasing in both H and B")
    h = PchipInterpolator(B, H)
    b = np.linspace(0.0, B[-1], n)
    nu = np.empty(n)
    nu[1:] = h(b[1:]) / b[1:]
    nu[0] = float(h.derivative()(0.0))                    # lim H/B as B -> 0
    b2 = b ** 2
    # the curve as GetDP will interpolate it: H = nu(B^2) B must increase with B
    x = np.linspace(1e-4, B[-1], 20000)
    f = Akima1DInterpolator(b2, nu) if check == "akima" else (lambda q: np.interp(q, b2, nu))
    hh = f(x ** 2) * x
    if not np.all(np.diff(hh) > 0):
        bad = x[1:][np.diff(hh) <= 0]
        raise BackendError(f"interpolated B-H curve is not monotone between {bad.min():.3f} and {bad.max():.3f} T")
    return b2, nu


def bh_issues(curves: dict, newton: bool = True) -> list[str]:
    """Problems with B-H curves as this backend will use them (nu_table), one message per material.
    The interpolation decides what is physical, so the check lives here rather than on the material."""
    issues = []
    for mid, c in curves.items():
        try:
            nu_table(c["H"], c["B"], check="akima" if newton else "linear")
        except BackendError as e:
            issues.append(f"material {mid}: {e}")
    return issues


def _bh_curves(design) -> dict:
    """{material id: {"H": [...], "B": [...]}} for every material with a B-H curve in the design's solids."""
    out = {}
    for slot in design.slots:
        s = design.part(slot).solid()
        if s is None:
            continue
        for node in _walk(s):
            m = node.material
            if hasattr(m, "has") and m.has("bh_curve"):
                t = m.bh_curve
                out[m.id] = {"H": list(map(float, t["H"])), "B": list(map(float, t["B"]))}
    return out


def _solid_canon(s: Solid) -> dict:
    d = s.canonical()
    d["surfaces"] = s.surfaces
    d["children"] = [_solid_canon(c) for c in s.children]
    return d


def _solid_from(d: dict) -> Solid:
    return Solid(d["op"], d["args"], [_solid_from(c) for c in d.get("children", [])], d.get("material"),
                 d.get("names"), d.get("excitation"), d.get("surfaces") or {})


def _mat_mu(mat) -> float:
    p = (mat or {}).get("props", {}).get("mu_r_linear") if isinstance(mat, dict) else None
    return float(p["value"]) if isinstance(p, dict) else (float(p) if p is not None else 1.0)


class GetDP3D(Backend):
    name = "getdp_3d"
    version = "1.1.0"
    capabilities = Capabilities(dims=3, symmetry="none", superposable=True)
    measure_needs_raw = True
    FIDELITY = {
        "nonlinear": Param(False),
        "ramp": Param("0.5, 0.8, 0.9, 1.0"),             # current ramp for nonlinear solves
        "mesh.h_fine": Param(1.0 * mm, dim="length"),
        "mesh.h_iron": Param(3.0 * mm, dim="length"),
        "mesh.h_far": Param(60 * mm, dim="length"),
        "mesh.fine_r_max": Param(45 * mm, dim="length"),
        "mesh.fine_z_min": Param(-48 * mm, dim="length"),
        "mesh.fine_z_max": Param(20 * mm, dim="length"),
        "mesh.transition": Param(30 * mm, dim="length"),
        "air_radius": Param(300 * mm, dim="length"),
        "air_center_z": Param(None, dim="length"),
        "nl.method": Param("newton", choices=["newton", "picard"]),
        "nl.relax": Param(1.0),
        "nl.tol_rel": Param(1e-4),
        "nl.iter_max": Param(60),
    }

    def check(self, design, stage: StageConfig) -> list[str]:
        missing = [s for s in design.slots if design.part(s).type_cls.solid_3d is None]
        if missing:
            return [f"part(s) without solid_3d: {', '.join(missing)}"]
        f = stage.fidelity
        if not f.get("nonlinear"):
            return []
        # B-H curves as this backend will interpolate them; runs per design before any mesh is built
        return bh_issues(_bh_curves(design), newton=f.get("nl.method", "newton") == "newton")

    def solve_inputs(self, design, stage: StageConfig) -> dict:
        bodies, bh, circuits = [], {}, set()
        nonlinear = bool(stage.fidelity.get("nonlinear"))
        for slot in design.slots:
            part = design.part(slot)
            s = part.solid()
            if s is None:
                raise BackendError(f"part {slot} ({part.type_id}) has no solid_3d")
            bodies.append({"slot": slot, "at": float(part.at), "solid": _solid_canon(s)})
            for node in _walk(s):
                if node.excitation:
                    circuits.add(node.excitation["circuit"])
        bh = _bh_curves(design) if nonlinear else {}
        fid = {k: v for k, v in stage.fidelity.items()}
        return {"bodies": bodies, "circuits": sorted(circuits), "fidelity": fid, "bh": bh}

    # ---- prepare ---------------------------------------------------------------------------------------
    def prepare(self, inputs: dict, workdir: Path) -> None:
        import gmsh
        workdir = Path(workdir)
        f = inputs["fidelity"]
        gmsh.initialize(["-noenv"])
        try:
            gmsh.option.setNumber("General.Terminal", 0)
            gmsh.model.add("m3d")
            occ = gmsh.model.occ
            bodies = []
            for b in inputs["bodies"]:
                bodies += realise(occ, _solid_from(b["solid"]), dz=b["at"], name=b["slot"])
            occ.synchronize()
            zs = []
            for bd in bodies:
                for t in bd.tags:
                    bb = gmsh.model.getBoundingBox(3, t)
                    zs += [bb[2], bb[5]]
            zc = f.get("air_center_z")
            zc = (min(zs) + max(zs)) / 2 if zc is None else zc
            air = occ.addSphere(0, 0, zc, f["air_radius"])
            occ.synchronize()
            inputs_dt = [[(3, t) for t in bd.tags] for bd in bodies]
            flat = [dt for lst in inputs_dt for dt in lst] + [(3, air)]
            _, omap = occ.fragment(flat, [])
            occ.synchronize()
            owner: dict[int, int] = {}
            k = 0
            for i, lst in enumerate(inputs_dt):
                for _ in lst:
                    for _, t in omap[k]:
                        if t in owner and owner[t] != i:
                            raise BackendError(f"bodies {bodies[owner[t]].name} and {bodies[i].name} overlap")
                        owner[t] = i
                    k += 1
            air_tags = [t for _, t in omap[k] if t not in owner]
            for i, bd in enumerate(bodies):
                gmsh.model.addPhysicalGroup(3, [t for t, o in owner.items() if o == i], i + 1)
            gmsh.model.addPhysicalGroup(3, air_tags, len(bodies) + 1)
            outer = gmsh.model.getBoundary([(3, t) for t in list(owner) + air_tags], combined=True, oriented=False)
            gmsh.model.addPhysicalGroup(2, [abs(t) for _, t in outer], BND)
            fld = gmsh.model.mesh.field
            fine = fld.add("Box")
            for key, v in (("VIn", f["mesh.h_fine"]), ("VOut", f["mesh.h_far"]), ("XMin", -f["mesh.fine_r_max"]),
                           ("XMax", f["mesh.fine_r_max"]), ("YMin", -f["mesh.fine_r_max"]),
                           ("YMax", f["mesh.fine_r_max"]), ("ZMin", f["mesh.fine_z_min"]),
                           ("ZMax", f["mesh.fine_z_max"]), ("Thickness", f["mesh.transition"])):
                fld.setNumber(fine, key, v)
            iron = fld.add("Box")
            xs = []
            for bd in bodies:
                for t in bd.tags:
                    bb = gmsh.model.getBoundingBox(3, t)
                    xs += [abs(bb[0]), abs(bb[3]), abs(bb[1]), abs(bb[4])]
            rmax = max(xs) + 5 * mm
            for key, v in (("VIn", f["mesh.h_iron"]), ("VOut", f["mesh.h_far"]), ("XMin", -rmax), ("XMax", rmax),
                           ("YMin", -rmax), ("YMax", rmax), ("ZMin", min(zs) - 5 * mm), ("ZMax", max(zs) + 20 * mm),
                           ("Thickness", f["mesh.transition"] * 2)):
                fld.setNumber(iron, key, v)
            mn = fld.add("Min")
            fld.setNumbers(mn, "FieldsList", [fine, iron])
            fld.setAsBackgroundMesh(mn)
            gmsh.option.setNumber("Mesh.MeshSizeFromPoints", 0)
            gmsh.option.setNumber("Mesh.MeshSizeExtendFromBoundary", 0)
            gmsh.option.setNumber("Mesh.MeshSizeFromCurvature", 0)
            gmsh.model.mesh.generate(3)
            gmsh.write(str(workdir / "mesh.msh"))
            n_elem = int(sum(len(e) for e in gmsh.model.mesh.getElements(3)[1]))
        finally:
            gmsh.finalize()
        self._regions_pro(inputs, bodies, workdir)
        shutil.copy(HERE / "mag3d.pro", workdir / "mag3d.pro")
        (workdir / "post.pro").write_text("// replaced per query\n")
        (workdir / "mesh_info.txt").write_text(f"elements {n_elem}\n")
        import json
        (workdir / "bodies.json").write_text(json.dumps([{"name": b.name, "group": i + 1} for i, b in
                                                         enumerate(bodies)]))

    def _regions_pro(self, inputs, bodies, workdir: Path):
        f = inputs["fidelity"]
        nonlinear = bool(f.get("nonlinear"))
        newton = nonlinear and f.get("nl.method", "newton") == "newton"
        interp = "InterpolationAkima" if newton else "InterpolationLinear"
        L = ["// generated by bplsim getdp_3d", f"NonLinear = {int(nonlinear)};", f"Newton = {int(newton)};",
             "Group {"]
        air, lin, nl, wind = [f"{len(bodies) + 1}"], [], [], []
        for i, bd in enumerate(bodies):
            L.append(f"  R{i} = Region[{i + 1}];  // {bd.name}")
            mat = bd.material if isinstance(bd.material, dict) else {}
            if bd.excitation:
                wind.append(f"R{i}")
            elif nonlinear and mat.get("id") in inputs["bh"]:
                nl.append(f"R{i}")
            elif _mat_mu(mat) != 1.0:
                lin.append(f"R{i}")
            else:
                air.append(f"R{i}")
        L += [f"  Air = Region[{{{', '.join(air)}}}];", f"  IronLin = Region[{{{', '.join(lin)}}}];",
              f"  IronNL = Region[{{{', '.join(nl)}}}];", f"  Windings = Region[{{{', '.join(wind)}}}];",
              "  Domain = Region[{Air, IronLin, IronNL, Windings}];", f"  Bnd = Region[{BND}];", "}"]
        consts = ", ".join(f"I_{_ident(c)} = 0" for c in inputs["circuits"]) or "I_none = 0"
        L.append(f"DefineConstant[ {consts} ];")
        ramp = [float(x) for x in str(f.get("ramp", "1.0")).split(",")] if nonlinear else [1.0]
        L.append("mu0 = 4e-7 * Pi;")
        L.append("Function {")
        L.append(f"  RampFrac() = {{{', '.join(repr(x) for x in ramp)}}};")
        L.append("  nu[Region[{Air, Windings}]] = 1 / mu0;")
        for i, bd in enumerate(bodies):
            if f"R{i}" in lin:
                L.append(f"  nu[R{i}] = 1 / (mu0 * {_mat_mu(bd.material)!r});")
        for mid, curve in inputs["bh"].items():
            b2, nu = nu_table(curve["H"], curve["B"], check="akima" if newton else "linear")
            pairs = ", ".join(f"{float(x)!r}, {float(y)!r}" for x, y in zip(b2, nu))
            name = "nu_" + _ident(mid)
            L.append(f"  {name}_list() = {{{pairs}}};")
            L.append(f"  {name}[] = {interp}[SquNorm[$1]]{{{name}_list()}};")
            if newton:
                # h = nu(|b|^2) b  ->  dh/db = nu I + 2 nu'(|b|^2) b (x) b; JacNL carries the second part
                L.append(f"  d{name}[] = d{interp}[SquNorm[$1]]{{{name}_list()}};")
        for i, bd in enumerate(bodies):
            mat = bd.material if isinstance(bd.material, dict) else {}
            if f"R{i}" in nl:
                L.append(f"  nu[R{i}] = nu_{_ident(mat['id'])}[$1];")
                if newton:
                    L.append(f"  dhdb[R{i}] = 2 * dnu_{_ident(mat['id'])}[$1#1] * SquDyadicProduct[#1];")
        for i, bd in enumerate(bodies):
            exc = bd.excitation
            if not exc:
                continue
            if bd.section_area <= 0:
                raise BackendError(f"winding {bd.name}: cannot determine its cross-section area")
            j = exc.get("sign", 1) * exc["turns"] / bd.section_area
            cx, cy = bd.axis_xy
            rho = f"Sqrt[(X[]-({cx!r}))^2 + (Y[]-({cy!r}))^2]"
            L.append(f"  Js[R{i}] = ({j!r} * I_{_ident(exc['circuit'])} / {rho}) * "
                     f"Vector[-(Y[]-({cy!r})), (X[]-({cx!r})), 0];")
        L.append("}")
        (workdir / "regions.pro").write_text("\n".join(L) + "\n")

    # ---- execute --------------------------------------------------------------------------------------
    def execute(self, inputs: dict, workdir: Path, basis: Basis, resources: dict) -> ExecResult:
        workdir = Path(workdir)
        f = inputs["fidelity"]
        cmd = [_getdp(), "mag3d.pro", "-msh", "mesh.msh", "-solve", "Res", "-v", "3",
               "-setnumber", "NL_tol_rel", repr(float(f.get("nl.tol_rel", 1e-4))),
               "-setnumber", "NL_iter_max", repr(float(f.get("nl.iter_max", 60))),
               "-setnumber", "NL_relax", repr(float(f.get("nl.relax", 1.0)))]
        for c, i in basis.currents.items():
            cmd += ["-setnumber", f"I_{_ident(c)}", repr(float(i))]
        timeout = float(resources.get("timeout") or 6 * 3600)
        try:
            r = subprocess.run(cmd, cwd=workdir, capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            return ExecResult("failed", f"getdp timed out after {timeout:.0f} s")
        log = r.stdout + r.stderr
        (workdir / f"solve_{basis.name}.log").write_text(log)
        if r.returncode != 0 or not (workdir / "mag3d.res").exists():
            return ExecResult("failed", f"getdp failed: {log[-1500:]}")
        # an unconverged nonlinear solve must never be stored as a result
        bad = [ln.strip() for ln in log.splitlines() if "did NOT converge" in ln]
        stalled = []
        if f.get("nonlinear") and f.get("nl.method") == "picard":
            import re
            tol = float(f.get("nl.tol_rel", 1e-4))
            for m in re.finditer(r"ramp step (\S+): (\S+) iterations, relative residual ([-+0-9.eE]+)", log):
                if float(m.group(3)) > tol:
                    stalled.append(m.group(0))
        if bad or stalled:
            return ExecResult("failed", "nonlinear solve did not converge: " + "; ".join(bad + stalled)
                              + " (try a finer fidelity.ramp, nl.relax < 1, or more nl.iter_max)")
        (workdir / "mag3d.res").replace(workdir / f"basis_{basis.name}.res")
        return ExecResult()

    def field_access(self, inputs: dict, workdir: Path, basis: Basis) -> FieldAccess:
        return GetDP3DField(Path(workdir), basis, inputs)


def _walk(s: Solid):
    yield s
    for c in s.children:
        yield from _walk(c)


class GetDP3DField(FieldAccess):
    symmetry = "none"

    def __init__(self, workdir: Path, basis: Basis, inputs: dict):
        self.dir, self.basis, self.inputs = workdir, basis, inputs
        self.res = workdir / f"basis_{basis.name}.res"
        if not self.res.exists():
            raise BackendError(f"no solution for basis {basis.name} in {workdir} (raw output purged?)")
        self._n = 0

    def _post(self, body: str) -> Path:
        self._n += 1
        out = f"q{self._n}.txt"
        (self.dir / "post.pro").write_text("PostOperation {\n  { Name Q; NameOfPostProcessing PP;\n    Operation {\n"
                                           + body.replace("@OUT@", out) + "\n    }\n  }\n}\n")
        r = subprocess.run([_getdp(), "mag3d.pro", "-msh", "mesh.msh", "-res", self.res.name, "-pos", "Q", "-v", "2"],
                           cwd=self.dir, capture_output=True, text=True, timeout=6 * 3600)
        path = self.dir / out
        if r.returncode != 0 or not path.exists():
            raise BackendError(f"getdp post-processing failed: {(r.stdout + r.stderr)[-1500:]}")
        return path

    def _elements(self, groups: list[int] | None = None) -> np.ndarray:
        key = "all" if groups is None else "_".join(map(str, groups))
        cache = self.dir / f"elem_{self.basis.name}_{key}.npy"
        if cache.exists():
            return np.load(cache)
        where = "Domain" if groups is None else f"Region[{{{', '.join(map(str, groups))}}}]"
        path = self._post(f'      Print[ b, OnElementsOf {where}, Depth 1, File "@OUT@", Format SimpleTable ];')
        import pandas as pd
        a = pd.read_csv(path, sep=r"\s+", header=None).to_numpy(float)
        path.unlink()
        np.save(cache, a)
        return a

    @staticmethod
    def _split(e: np.ndarray):
        P = e[:, :12].reshape(-1, 4, 3)
        B = e[:, 12:24].reshape(-1, 4, 3)
        return P, B

    def _interp(self, xyz: np.ndarray) -> np.ndarray:
        """Locate each point in its tetrahedron (nearest-centroid candidates, widened for misses) and
        interpolate GetDP's nodal B; points on shared faces get the mean of the containing elements."""
        from scipy.spatial import cKDTree
        if not hasattr(self, "_mesh"):
            P, B = self._split(self._elements())
            self._mesh = (P, B, cKDTree(P.mean(axis=1)))
        P, B, tree = self._mesh
        out = np.full((len(xyz), 3), np.nan)
        todo = np.arange(len(xyz))
        for k in (16, 64, 256):
            if not len(todo):
                break
            pts = xyz[todo]
            _, cand = tree.query(pts, k=min(k, len(P)))
            p0 = P[cand, 0]
            T = np.stack([P[cand, 1] - p0, P[cand, 2] - p0, P[cand, 3] - p0], axis=-1)
            rhs = (pts[:, None, :] - p0)[..., None]
            det = np.linalg.det(T)
            T = np.where(np.abs(det)[..., None, None] > 1e-30, T, np.eye(3))
            lam123 = np.linalg.solve(T, rhs)[..., 0]
            lam = np.concatenate([1 - lam123.sum(-1, keepdims=True), lam123], axis=-1)
            inside = np.all(lam >= -1e-7, axis=-1) & (np.abs(det) > 1e-30)
            found = inside.any(axis=1)
            vals = (np.clip(lam, 0, None)[..., None] * B[cand]).sum(axis=2)
            w = inside.astype(float)
            ok = np.flatnonzero(found)
            out[todo[ok]] = (vals[ok] * w[ok, :, None]).sum(axis=1) / w[ok].sum(axis=1)[:, None]
            todo = todo[~found]
        if len(todo):
            raise BackendError(f"{len(todo)} sample point(s) outside the mesh, e.g. {xyz[todo[0]]}")
        return out

    def sample(self, where, fields=("B",)):
        from ...measure.data import ProbeData
        r, th, z = np.ravel(where.r), np.ravel(where.theta), np.ravel(where.z)
        xyz = np.column_stack([r * np.cos(th), r * np.sin(th), z])
        b = self._interp(xyz)
        c, s = np.cos(th), np.sin(th)
        br = b[:, 0] * c + b[:, 1] * s
        bt = -b[:, 0] * s + b[:, 1] * c
        shape = where.shape
        return ProbeData({"r": where.r, "theta": where.theta, "z": where.z},
                         {"B_r": br.reshape(shape), "B_theta": bt.reshape(shape), "B_z": b[:, 2].reshape(shape)},
                         {"symmetry": "none"}, where.axes)

    def _groups_of(self, slot: str) -> list[int]:
        import json
        bodies = json.loads((self.dir / "bodies.json").read_text())
        return [b["group"] for b in bodies if b["name"] == slot or b["name"].startswith(slot + ".")]

    def region(self, part: str, fields=("B",)):
        from ...measure.data import ProbeData
        groups = self._groups_of(part)
        if not groups:
            raise BackendError(f"no body for part {part!r}")
        P, B = self._split(self._elements(groups))
        c = P.mean(axis=1)
        v = np.abs(np.einsum("ni,ni->n", np.cross(P[:, 1] - P[:, 0], P[:, 2] - P[:, 0]), P[:, 3] - P[:, 0])) / 6
        b = B.mean(axis=1)
        r = np.hypot(c[:, 0], c[:, 1])
        th = np.arctan2(c[:, 1], c[:, 0])
        br = b[:, 0] * np.cos(th) + b[:, 1] * np.sin(th)
        bt = -b[:, 0] * np.sin(th) + b[:, 1] * np.cos(th)
        return ProbeData({"r": r, "theta": th, "z": c[:, 2], "weight": v},
                         {"B_r": br, "B_theta": bt, "B_z": b[:, 2]}, {"symmetry": "none"})

    def boundary(self, surface: str, fields=("B",), n_theta: int = 36):
        """B just outside a named surface of an axisymmetric (revolved) part, at n_theta angles."""
        from ...measure.data import ProbeData
        from shapely.geometry import Point, Polygon
        slot, name = surface.split(".", 1)
        body = next((b for b in self.inputs["bodies"] if b["slot"] == slot), None)
        if body is None or body["solid"]["op"] != "revolve" or name not in (body["solid"].get("surfaces") or {}):
            raise BackendError(f"no revolved surface {surface!r}")
        pts = [(r, z + body["at"]) for r, z in body["solid"]["args"]["points"][0]]
        poly = Polygon(pts)
        rs, zs, nr_, nz_, ws = [], [], [], [], []
        for i in body["solid"]["surfaces"][name]:
            (ra, za), (rb, zb) = pts[i], pts[(i + 1) % len(pts)]
            L = math.hypot(rb - ra, zb - za)
            nr, nz = (zb - za) / L, -(rb - ra) / L
            if poly.contains(Point((ra + rb) / 2 + 1e-7 * nr, (za + zb) / 2 + 1e-7 * nz)):
                nr, nz = -nr, -nz
            for s_ in range(8):
                t = (s_ + 0.5) / 8
                rs.append(ra + t * (rb - ra) + 1e-6 * nr)
                zs.append(za + t * (zb - za) + 1e-6 * nz)
                nr_.append(nr)
                nz_.append(nz)
                ws.append(2 * math.pi * (ra + t * (rb - ra)) * L / 8 / n_theta)
        th = np.arange(n_theta) * 2 * math.pi / n_theta
        R, TH = np.meshgrid(rs, th, indexing="ij")
        Z, _ = np.meshgrid(zs, th, indexing="ij")
        from ...probes import points
        d = self.sample(points(R.ravel(), TH.ravel(), Z.ravel()))
        rep = lambda a: np.repeat(np.array(a), n_theta)  # noqa: E731
        return ProbeData({"r": d.coords["r"], "theta": d.coords["theta"], "z": d.coords["z"], "n_r": rep(nr_),
                          "n_z": rep(nz_), "weight": rep(ws)}, d.fields, {"symmetry": "none"})

    def export_grid(self, grid, fields=("B",), fmt="npz", path=None):
        xs = np.arange(grid["x"][0], grid["x"][1] + 1e-12, grid["spacing"])
        ys = np.arange(grid["y"][0], grid["y"][1] + 1e-12, grid["spacing"])
        zs = np.arange(grid["z"][0], grid["z"][1] + 1e-12, grid["spacing"])
        X, Y, Z = np.meshgrid(xs, ys, zs, indexing="ij")
        b = self._interp(np.column_stack([X.ravel(), Y.ravel(), Z.ravel()])).reshape(X.shape + (3,))
        if fmt == "openpmd":
            from ...measure.openpmd import write_field
            write_field(path, {"x": xs, "y": ys, "z": zs}, {"B": b})
        else:
            np.savez(path, x=xs, y=ys, z=zs, B_x=b[..., 0], B_y=b[..., 1], B_z=b[..., 2])
        return path
