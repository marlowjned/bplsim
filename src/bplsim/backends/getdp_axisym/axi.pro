// axi.pro (bplsim getdp_axisym)
//
// 2-D axisymmetric linear magnetostatics, a-formulation (a = a_phi, Form1P perpendicular edges, VolAxiSqu
// Jacobian): the axisymmetric branch of GetDP's templates/Lib_Magnetostatics_a_phi.pro, as in the legacy
// gmsh_getdp/axisym/axisym.pro. Gmsh plane: x = r, y = z (thruster axis, +z downstream).
//
// regions.pro (generated) defines the groups Air, Mag, Windings, Domain, Bnd, the reluctivity nu[] per
// region and the source js[] per winding region in terms of the circuit currents I_<circuit>, which are
// set per basis with -setnumber.

Include "regions.pro";

Jacobian {
  { Name JVol; Case { { Region All; Jacobian VolAxiSqu; } } }
}

Integration {
  { Name Int; Case { { Type Gauss; Case { { GeoElement Triangle; NumberOfPoints 4; }
                                           { GeoElement Line; NumberOfPoints 4; } } } } }
}

Constraint {
  { Name A0; Case { { Region Bnd; Value 0; } } }
}

FunctionSpace {
  { Name Hcurl_a; Type Form1P;
    BasisFunction {
      { Name se; NameOfCoef ae; Function BF_PerpendicularEdge; Support Domain; Entity NodesOf[All]; }
    }
    Constraint { { NameOfCoef ae; EntityType NodesOf; NameOfConstraint A0; } }
  }
}

Formulation {
  { Name MS; Type FemEquation;
    Quantity { { Name a; Type Local; NameOfSpace Hcurl_a; } }
    Equation {
      Integral { [ nu[] * Dof{d a}, {d a} ]; In Domain; Jacobian JVol; Integration Int; }
      Integral { [ -js[], {a} ]; In Windings; Jacobian JVol; Integration Int; }
    }
  }
}

Resolution {
  { Name Res; System { { Name S; NameOfFormulation MS; } }
    Operation { Generate[S]; Solve[S]; SaveSolution[S]; } }
}

PostProcessing {
  { Name PP; NameOfFormulation MS;
    Quantity {
      { Name b;   Value { Local { [ {d a} ]; In Domain; Jacobian JVol; } } }
      { Name raz; Value { Local { [ CompZ[{a}] * X[] ]; In Domain; Jacobian JVol; } } }
      { Name energy; Value { Integral { [ 0.5 * nu[] * SquNorm[{d a}] ]; In Domain; Jacobian JVol;
                                        Integration Int; } } }
    }
  }
}

Include "post.pro";
