// mag3d.pro (bplsim getdp_3d)
//
// 3-D magnetostatics, vector-potential formulation with edge elements and a tree-cotree gauge: the
// formulation of the legacy gmsh_getdp/assembly/magnetostatics_assembly.pro. Linear iron (nu constant)
// or nonlinear iron (nu(|b|^2) interpolated from each material's B-H curve) with a current ramp and Picard
// iterations. regions.pro (generated) defines Air, IronLin, IronNL, Windings, Domain, Bnd, nu[] and Js[]
// (in terms of the circuit currents I_<circuit>, set per basis with -setnumber).

Include "regions.pro";

DefineConstant[ NL_tol_abs = 1e-6, NL_tol_rel = 1e-4, NL_iter_max = 60, NL_relax = 1.0 ];
// Newton (regions.pro sets Newton = 1 for nonlinear solves by default): the B-H tangent dh/db as a JacNL
// term, increments solved with GenerateJac/SolveJac, B-H interpolated with Akima (continuous tangent).
// GetDP 3.5 segfaults on a plain Generate when the formulation holds a JacNL term, so the Newton path
// assembles only through GenerateJac (both notes from the legacy assembly pipeline, 2026-10-06).

Jacobian { { Name JVol; Case { { Region All; Jacobian Vol; } } } }

Integration {
  { Name Int1; Case { { Type Gauss; Case { { GeoElement Tetrahedron; NumberOfPoints 4; }
                                           { GeoElement Triangle; NumberOfPoints 3; } } } } }
}

Constraint {
  { Name MVP_0; Case { { Region Bnd; Value 0; } } }
  { Name MVP_Gauge; Case { { Region Domain; SubRegion Bnd; Value 0.; } } }
}

FunctionSpace {
  { Name Hcurl_a; Type Form1;
    BasisFunction { { Name se; NameOfCoef ae; Function BF_Edge; Support Domain; Entity EdgesOf[All]; } }
    Constraint {
      { NameOfCoef ae; EntityType EdgesOf; NameOfConstraint MVP_0; }
      { NameOfCoef ae; EntityType EdgesOfTreeIn; EntitySubType StartingOn; NameOfConstraint MVP_Gauge; }
    }
  }
}

Formulation {
  { Name MS; Type FemEquation;
    Quantity { { Name a; Type Local; NameOfSpace Hcurl_a; } }
    Equation {
      Galerkin { [ nu[] * Dof{d a}, {d a} ]; In Region[{Air, Windings, IronLin}]; Jacobian JVol; Integration Int1; }
      Galerkin { [ nu[{d a}] * Dof{d a}, {d a} ]; In IronNL; Jacobian JVol; Integration Int1; }
      If(Newton)
        Galerkin { JacNL[ dhdb[{d a}] * Dof{d a}, {d a} ]; In IronNL; Jacobian JVol; Integration Int1; }
      EndIf
      Galerkin { [ -$IFrac * Js[], {a} ]; In Windings; Jacobian JVol; Integration Int1; }
    }
  }
}

Resolution {
  { Name Res; System { { Name S; NameOfFormulation MS; } }
    Operation {
      InitSolution[S];
      If(NonLinear && Newton)
      For n In {0:#RampFrac()-1}
        Evaluate[ $IFrac = RampFrac(n) ];
        IterativeLoop[NL_iter_max, NL_tol_rel, NL_relax]{ GenerateJac[S]; SolveJac[S]; }
        Print[{n}, Format "ramp step %g: Newton done"];
      EndFor
      Else
      For n In {0:#RampFrac()-1}
        Evaluate[ $IFrac = RampFrac(n) ];
        Generate[S]; Solve[S];
        If(NonLinear)
          Generate[S]; GetResidual[S, $res0];
          Evaluate[ $res = $res0, $iter = 0 ];
          While[$res > NL_tol_abs && $res / $res0 > NL_tol_rel && $res / $res0 <= 1 && $iter < NL_iter_max]{
            Solve[S]; Generate[S]; GetResidual[S, $res];
            Evaluate[ $iter = $iter + 1 ];
          }
          Print[{n, $iter, $res / $res0}, Format "ramp step %g: %g iterations, relative residual %g"];
        EndIf
      EndFor
      EndIf
      SaveSolution[S];
    }
  }
}

PostProcessing {
  { Name PP; NameOfFormulation MS;
    Quantity { { Name b; Value { Local { [ {d a} ]; In Domain; Jacobian JVol; } } } }
  }
}

Include "post.pro";
