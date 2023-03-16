"""
Implementation of double-layer models
"""
from abc import abstractmethod
from dataclasses import dataclass

import numpy as np
from scipy.integrate import solve_bvp

import constants as C
import langevin as L


@dataclass
class SpatialProfilesSolution:
    """
    Dataclass to store double-layer model solution data
    x: position, nm
    phi: potential, V
    efield: electric field, V/m
    c_dict: dict of concentration profiles of form {'name of species': np.ndarray}
    eps: relative permittivity
    name: name of the model
    """
    x:       np.ndarray # pylint: disable=invalid-name
    phi:     np.ndarray
    efield:  np.ndarray
    c_dict:  dict
    eps:     np.ndarray
    name:    str


@dataclass
class PotentialSweepSolution:
    """
    Data class to store potential sweep solution data, e.g. differential capacitance
    phi: potential range, V
    charge: calculated surface charge, C/m^2
    cap: differential capacitance, uF/cm^2
    """
    phi:        np.ndarray
    charge:     np.ndarray
    cap:        np.ndarray
    profiles:   list
    name:       str


def k_fraction(k_a, k_b, conc):
    """
    Shorthand for the fraction with Ka's and Kb's in the insulator boundary
    condition
    """
    return (conc**2 - k_a * k_b) / (k_a * k_b + k_b * conc + conc**2)


class DoubleLayerModel:
    """
    Base class for an ODE. Implements basic features, but leaves
    RHS of ODE and the definition of number densities abstract.
    """
    def __init__(self, ion_concentration_molar: float) -> None:
        self.c_0 = ion_concentration_molar
        self.n_0 = self.c_0 * 1e3 * C.N_A
        self.kappa_debye = np.sqrt(2*self.n_0*(C.Z*C.E_0)**2 /
                                   (C.EPS_R_WATER*C.EPS_0*C.K_B*C.T))
        self.name = 'Unnamed'

    def create_x_mesh(self, xmax_nm, n_points):
        """
        Get a logarithmically spaced x-axis, fine mesh close to electrode
        """
        max_exponent = np.log10(xmax_nm)
        x_nm = np.logspace(-6, max_exponent, n_points) - 1e-6
        return self.kappa_debye * 1e-9 * x_nm

    @abstractmethod
    def ode_rhs(self, x, y, p_h=7):  # pylint: disable=unused-argument, invalid-name
        """
        Function to pass to ODE solver, specifying the right-hand side of the
        system of dimensionless 1st order ODE's that we solve.
        x: dimensionless x-axis of length n, i.e. kappa (1/m) times x-position (m).
        y: dimensionless potential phi and dphi/dx, size 2 x n.
        """

    def ode_lambda(self, p_h=7):
        """
        Get an ODE RHS function to pass to Scipy's solve_bvp; using lambda gives
        the possibility to include specific parameters like pH in derived classes
        """
        return lambda x, y: self.ode_rhs(x, y, p_h)

    def dirichlet_lambda(self, phi0):
        """
        Return a boundary condition function to pass to scipy's solve_bvp
        """
        return lambda ya, yb: np.array([ya[0] - C.BETA * C.Z * C.E_0 * phi0, yb[0]])

    def potential_sequential_solve(self,
                         ode_lambda: callable,
                         potential: np.ndarray,
                         tol: float=1e-3,
                         p_h: float=7):
        """
        Sweep over a boundary condition parameter array (potential, pH) and use the previous
        solution as initial condition for the next. The initial condition assumes that we
        start at the PZC.

        Returns: charge for each parameter; list of SpatialProfilesSolutions
        """
        chg = np.zeros(potential.shape)
        profile_list = []
        max_res = np.zeros(potential.shape)

        x_axis = self.create_x_mesh(100, 1000)
        y_initial = np.zeros((2, x_axis.shape[0]))

        for i, phi in enumerate(potential):
            sol = solve_bvp(
                ode_lambda(p_h),
                self.dirichlet_lambda(phi),
                x_axis,
                y_initial,
                tol=tol,
                max_nodes=int(1e8),
                verbose=0)
            prf = self.compute_profiles(sol)
            chg[i] = prf.efield[0] * C.EPS_0 * prf.eps[0]
            max_res[i] = np.max(sol.rms_residuals)
            profile_list.append(prf)

            x_axis = sol.x
            y_initial = sol.y

        print(f"Sweep from {potential[0]:.2f}V to {potential[-1]:.2f}V. " \
            + f"Maximum relative residual: {np.max(max_res):.5e}.")
        return chg, profile_list

    def potential_sweep(self, potential: np.ndarray, tol: float=1e-3, p_h=7):
        """
        Numerical solution to a potential sweep for a defined double-layer model.
        """
        # Find potential closest to PZC
        i_pzc = np.argmin(np.abs(potential)).squeeze()

        chg = np.zeros(potential.shape)
        chg_neg, profiles_neg = self.potential_sequential_solve(
            self.ode_lambda,
            potential[i_pzc::-1],
            tol=tol,
            p_h=p_h)
        chg[:i_pzc+1] = chg_neg[::-1]
        chg[i_pzc:], profiles_pos = self.potential_sequential_solve(
            self.ode_lambda,
            potential[i_pzc::1],
            tol)

        cap = np.gradient(chg, edge_order=2)/np.gradient(potential) * 1e2
        sol = PotentialSweepSolution(phi=potential,
                                     charge=chg,
                                     cap=cap,
                                     profiles=profiles_neg[::-1] + profiles_pos,
                                     name=self.name)
        return sol

    def spatial_profiles(self, phi0: float, tol: float=1e-3, p_h=7):
        """
        Get spatial profiles solution struct.
        """
        sign = phi0/abs(phi0)
        _, profiles = self.potential_sequential_solve(self.ode_lambda,
                                                      np.arange(0, phi0, sign*0.01),
                                                      tol=tol,
                                                      p_h=p_h)
        return profiles[-1]

    @abstractmethod
    def compute_profiles(self, sol) -> SpatialProfilesSolution:
        """
        Convert a dimensionless scipy solution into dimensional spatial
        profiles
        """


class GouyChapman(DoubleLayerModel):
    """
    Gouy-Chapman model, treating ions as point particles obeying Boltzmann statistics.
    See for example Schmickler & Santos' Interfacial Electrochemistry.
    """
    def __init__(self, ion_concentration_molar: float) -> None:
        super().__init__(ion_concentration_molar)
        self.name = f'Gouy-Chapman {self.c_0:.3f}M'

    def ode_rhs(self, x, y, p_h=7):
        dy1 = y[1, :]
        dy2 = np.sinh(y[0, :])
        return np.vstack([dy1, dy2])

    def compute_profiles(self, sol):
        ret = SpatialProfilesSolution(
            x=sol.x / self.kappa_debye * 1e9,
            phi=sol.y[0, :] / (C.BETA * C.Z * C.E_0),
            efield=-sol.y[1, :] * self.kappa_debye / (C.BETA * C.Z * C.E_0),
            c_dict={
                'Cations': self.c_0 * np.exp(-sol.y[0, :]),
                'Anions': self.c_0 * np.exp(sol.y[0, :]),
                'Solvent': np.zeros(sol.x.shape)},
            eps=np.ones(sol.x.shape) * C.EPS_R_WATER,
            name=self.name)
        return ret

    def analytical_sweep(self, potential: np.ndarray):
        """
        Analytic solution to a potential sweep in the Gouy-Chapman model.

        ion_concentration_molar: bulk ion concentration in molar
        potential: potential array in V
        """
        cap = self.kappa_debye * C.EPS_R_WATER * C.EPS_0 * \
            np.cosh(C.BETA*C.Z*C.E_0 * potential / 2) * 1e2
        chg = np.sqrt(8 * self.n_0 * C.K_B * C.T * C.EPS_R_WATER * C.EPS_0) * \
            np.sinh(C.BETA * C.Z * C.E_0 * potential / 2)
        return PotentialSweepSolution(
            phi=potential, charge=chg, cap=cap, profiles=[], name=self.name + ' (Analytic)')


class Borukhov(DoubleLayerModel):
    """
    Model developed by Borukhov, Andelman and Orland, modifying the Guy-Chapman model to
    take finite ion size into account.
    https://doi.org/10.1016/S0013-4686(00)00576-4
    """
    def __init__(self, ion_concentration_molar: float, a_m: float) -> None:
        super().__init__(ion_concentration_molar)
        self.chi_0 = 2 * a_m ** 3 * self.n_0
        self.n_max = 1/a_m**3
        self.name = f'Borukhov {self.c_0:.3f}M {a_m*1e10:.1f}Å'

    def ode_rhs(self, x, y, p_h=7):
        dy1 = y[1, :]
        dy2 = np.sinh(y[0, :]) / (1 - self.chi_0 + self.chi_0 * np.cosh(y[0, :]))
        return np.vstack([dy1, dy2])

    def compute_profiles(self, sol):
        bf_c = np.exp(-sol.y[0, :])
        bf_a = np.exp(sol.y[0, :])
        denom = 1 - self.chi_0 + self.chi_0 * np.cosh(sol.y[0, :])

        # Return solution struct
        ret = SpatialProfilesSolution(
            x=sol.x / self.kappa_debye * 1e9,
            phi=sol.y[0, :] / (C.BETA * C.Z * C.E_0),
            efield=-sol.y[1, :] * self.kappa_debye / (C.BETA * C.Z * C.E_0),
            c_dict={
                'Cations': self.c_0 * bf_c / denom,
                'Anions': self.c_0 * bf_a / denom,
                'Solvent': np.zeros(sol.x.shape)
            },
            eps=np.ones(sol.x.shape) * C.EPS_R_WATER,
            name=self.name)
        return ret

    def analytical_sweep(self, potential: np.ndarray):
        """
        Analytic solution to a potential sweep in the Borukhov-Andelman-Orland model.

        ion_concentration_molar: bulk ion concentration in molar
        a_m: ion diameter in m
        potential: potential array in V
        """
        y_0 = C.BETA*C.Z*C.E_0*potential  # dimensionless potential
        chg = np.sqrt(4 * C.K_B * C.T * C.EPS_0 * C.EPS_R_WATER * self.n_0 / self.chi_0) \
            * np.sqrt(np.log(self.chi_0 * np.cosh(y_0) - self.chi_0 + 1)) * y_0 / np.abs(y_0)
        cap = np.sqrt(2) * self.kappa_debye * C.EPS_R_WATER * C.EPS_0 / np.sqrt(self.chi_0) \
            * self.chi_0 * np.sinh(np.abs(y_0)) \
            / (self.chi_0 * np.cosh(y_0) - self.chi_0 + 1) \
            / (2*np.sqrt(np.log(self.chi_0 * np.cosh(y_0) - self.chi_0 + 1))) \
            * 1e2 # uF/cm^2
        return PotentialSweepSolution(
            phi=potential, charge=chg, cap=cap, profiles=[], name=self.name + ' (Analytic)')


class Abrashkin(DoubleLayerModel):
    """
    Langevin-Poisson-Boltzmann model that was derived by Abrashkin, further developed by
    Gongadze & Iglic (here implemented without refractive index-dependent factors), and
    related to kinetics by Jun Huang.
    https://doi.org/10.1103/PhysRevLett.99.077801
    https://doi.org/10.1016/j.electacta.2015.07.179
    https://doi.org/10.1021/jacsau.1c00315
    """
    def __init__(self,
                 ion_concentration_molar: float,
                 gamma_c: float, gamma_a: float,
                 eps_r_opt=C.N_WATER**2) -> None:
        super().__init__(ion_concentration_molar)
        self.gamma_c = gamma_c
        self.gamma_a = gamma_a
        self.n_max = C.C_WATER_BULK * 1e3 * C.N_A
        n_s_0 = self.n_max - gamma_c * self.n_0 - gamma_a * self.n_0

        self.chi = self.n_0 / self.n_max
        self.chi_s = n_s_0 / self.n_max

        self.eps_r_opt = eps_r_opt

        p_water = np.sqrt(3 * (C.EPS_R_WATER - self.eps_r_opt) * C.EPS_0 / (C.BETA * self.n_max))
        self.p_tilde = p_water * self.kappa_debye / (C.Z * C.E_0)

        self.name = f'LPB {self.c_0:.3f}M {gamma_c:.1f}-{gamma_a:.1f}'

    def densities(self, sol_y):
        """
        Compute cation, anion and solvent densities.
        """
        bf_c = np.exp(-sol_y[0, :])
        bf_a = np.exp(+sol_y[0, :])
        bf_s = L.sinh_x_over_x(self.p_tilde * sol_y[1, :])
        denom = self.chi_s * bf_s + self.gamma_c * self.chi * bf_c + self.gamma_a * self.chi * bf_a
        n_cat = self.n_0 * bf_c / denom
        n_an  = self.n_0 * bf_a / denom
        n_sol = self.n_max * self.chi_s * bf_s / denom
        return n_cat, n_an, n_sol

    def ode_rhs(self, x, y, p_h=7):
        dy1 = y[1, :]
        n_cat, n_an, n_sol = self.densities(y)

        numer1 = n_an - n_cat
        numer2 = self.p_tilde * y[1, :] * L.langevin_x(self.p_tilde * y[1, :]) * \
            (self.gamma_a * n_an - self.gamma_c * n_cat) * n_sol/self.n_max
        denom1 = self.kappa_debye ** 2 * self.eps_r_opt * C.EPS_0 / (C.Z * C.E_0)**2 / C.BETA
        denom2 = self.p_tilde**2 * n_sol * L.d_langevin_x(self.p_tilde * y[1, :])
        denom3 = self.p_tilde**2 * L.langevin_x(self.p_tilde * y[1, :])**2 * \
            (self.gamma_c * n_cat + self.gamma_a * n_an) * n_sol/self.n_max

        dy2 = (numer1 + numer2) / (denom1 + denom2 + denom3)
        return np.vstack([dy1, dy2])

    def permittivity(self, sol_y):
        """
        Compute the permittivity using the electric field
        n_sol: solvent number density
        y_1: dimensionless electric field
        """
        sol_y = np.atleast_1d(sol_y).reshape(2, -1)
        _, _, n_sol = self.densities(sol_y)
        two_nref_over_epsrw = self.kappa_debye ** 2 * C.EPS_0 / (C.Z * C.E_0)**2 / C.BETA
        return self.eps_r_opt + \
               self.p_tilde**2 * n_sol / two_nref_over_epsrw * \
               L.langevin_x_over_x(self.p_tilde * sol_y[1, :])

    def compute_profiles(self, sol):
        n_cat, n_an, n_sol = self.densities(sol.y)

        # Return solution struct
        ret = SpatialProfilesSolution(
            x=sol.x / self.kappa_debye * 1e9,
            phi=sol.y[0, :] / (C.BETA * C.Z * C.E_0),
            efield=-sol.y[1, :] * self.kappa_debye / (C.BETA * C.Z * C.E_0),
            c_dict={
                'Cations': n_cat/1e3/C.N_A,
                'Anions': n_an/1e3/C.N_A,
                'Solvent': n_sol/1e3/C.N_A
            },
            eps=self.permittivity(sol.y),
            name=self.name)

        return ret


class ProtonLPB(DoubleLayerModel):
    """
    Taking into account protons and hydroxy ions
    """
    def __init__(self,
                 support_ion_concentration_molar: float,
                 gamma_c: float, gamma_a: float,
                 gamma_h: float, gamma_oh: float,
                 eps_r_opt=C.N_WATER**2) -> None:
        self.gammas = np.array([gamma_h, gamma_oh, gamma_c, gamma_a, 1]).reshape(5, 1)
        self.charge = np.array([+1, -1, +1, -1, 0]).reshape(5, 1)

        # Nondimensional quantities are based on debye length with support ion concentration
        super().__init__(support_ion_concentration_molar)
        self.n_max = C.C_WATER_BULK * 1e3 * C.N_A
        self.eps_r_opt = eps_r_opt
        self.kappa_debye = np.sqrt(2*self.n_max*(C.Z*C.E_0)**2 /
                                   (C.EPS_0*C.EPS_R_WATER*C.K_B*C.T))

        p_water = np.sqrt(3 * (C.EPS_R_WATER - self.eps_r_opt) * C.EPS_0 / (C.BETA * self.n_max))
        self.p_tilde = p_water * self.kappa_debye / (C.Z * C.E_0)

        self.name = f'pH-LPB {self.c_0:.3f}M {gamma_c:.1f}-{gamma_a:.1f}'

    def bulk_densities(self, p_h: float):
        """
        Compute bulk cation, anion and solvent densities.
        """
        # Compute bulk number densities
        c_bulk = np.zeros((5, 1))
        c_bulk[0] = 10 ** (- p_h)                         # [H+]
        c_bulk[1] = 10 ** (- C.PKW + p_h)                 # [OH-]
        c_bulk[2] = self.c_0 - c_bulk[0]                  # [Cat]
        c_bulk[3] = c_bulk[0] + c_bulk[2] - c_bulk[1]     # [An]
        c_bulk[4] = C.C_WATER_BULK - np.sum(self.gammas * c_bulk) # [H2O]
        n_bulk = c_bulk * 1e3 * C.N_A
        return n_bulk

    def boltzmann_factors(self, sol_y):
        """
        Compute cation, anion and solvent Boltzmann factors.
        """
        bf_pos = np.exp(-sol_y[0, :])
        bf_neg = np.exp(+sol_y[0, :])
        bf_sol = L.sinh_x_over_x(self.p_tilde * sol_y[1, :])
        bfs = np.array([bf_pos, bf_neg, bf_pos, bf_neg, bf_sol]) # shape (5, ...)
        return bfs

    def densities(self, sol_y: np.ndarray, p_h: float):
        """
        Compute cation, anion and solvent densities.
        """
        # Compute occupied volume fraction chi for each species
        n_bulk = self.bulk_densities(p_h)
        chi = n_bulk / self.n_max

        # Compute denominator
        bfs = self.boltzmann_factors(sol_y)
        denom = np.sum(self.gammas * chi * bfs, axis=0)

        # Compute profiles
        n_profile = n_bulk * bfs / denom

        return n_profile

    def get_denominator(self, sol_y: np.ndarray, p_h: float):
        """
        Get denominator of densities
        """
        n_bulk = self.bulk_densities(p_h)
        chi = n_bulk / self.n_max

        bfs = self.boltzmann_factors(sol_y)
        denom = np.sum(self.gammas * chi * bfs, axis=0)

        return denom

    def ode_rhs(self, x, y, p_h: float=7):
        dy1 = y[1, :]
        n_arr = self.densities(y, p_h)

        numer1 = np.sum(-self.charge * n_arr, axis=0)
        numer2 = self.p_tilde * y[1, :] * L.langevin_x(self.p_tilde * y[1, :]) * \
            np.sum(n_arr * -self.charge * self.gammas, axis=0) * n_arr[4]/self.n_max
        denom1 = self.kappa_debye ** 2 * self.eps_r_opt * C.EPS_0 / (C.Z * C.E_0)**2 / C.BETA
        denom2 = self.p_tilde**2 * n_arr[4] * L.d_langevin_x(self.p_tilde * y[1, :])
        denom3 = self.p_tilde**2 * L.langevin_x(self.p_tilde * y[1, :])**2 * \
            np.sum(n_arr * self.charge**2 * self.gammas, axis=0) * n_arr[4]/self.n_max

        dy2 = (numer1 + numer2) / (denom1 + denom2 + denom3)
        return np.vstack([dy1, dy2])

    def permittivity(self, sol_y: np.ndarray, n_sol: np.ndarray):
        """
        Compute the permittivity using the electric field
        n_sol: solvent number density
        y_1: dimensionless electric field
        """
        two_nref_over_epsrw = self.kappa_debye ** 2 * C.EPS_0 / (C.Z * C.E_0)**2 / C.BETA
        return self.eps_r_opt + \
               self.p_tilde**2 * n_sol / two_nref_over_epsrw * \
               L.langevin_x_over_x(self.p_tilde * sol_y[1, :])

    def compute_profiles(self, sol, p_h: float=7):
        n_arr = self.densities(sol.y, p_h)

        # Return solution struct
        ret = SpatialProfilesSolution(
            x=sol.x / self.kappa_debye * 1e9,
            phi=sol.y[0, :] / (C.BETA * C.Z * C.E_0),
            efield=-sol.y[1, :] * self.kappa_debye / (C.BETA * C.Z * C.E_0),
            c_dict={
                r'H$^+$': n_arr[0]/1e3/C.N_A,
                r'OH$^-$': n_arr[1]/1e3/C.N_A,
                'Cations': n_arr[2]/1e3/C.N_A,
                'Anions': n_arr[3]/1e3/C.N_A,
                'Solvent': n_arr[4]/1e3/C.N_A
            },
            eps=self.permittivity(sol.y, n_arr[4]),
            name=self.name)

        return ret

    def insulator_bc_lambda(self, p_h):
        """
        Return a boundary condition function to pass to scipy's solve_bvp
        """
        return lambda ya, yb: self.insulator_bc(ya, yb, p_h)

    def insulator_bc(self, ya, yb, p_h):
        """
        Boundary condition
        """
        #pylint: disable=invalid-name
        n_arr = self.densities(ya.reshape(2, 1), p_h)
        eps_r = self.permittivity(ya.reshape(2, 1), np.atleast_1d(n_arr[4]))

        c_bulk_arr = self.bulk_densities(p_h) / 1e3 / C.N_A

        left = 2 * eps_r * ya[1] \
            + self.kappa_debye * C.EPS_R_WATER * C.N_SITES_SILICA / self.n_max \
            * k_fraction(C.K_SILICA_A, C.K_SILICA_B, c_bulk_arr[0] * np.exp(-ya[0]))

        # left = None
        # if p_h < 7.0:
        #     left = 2 * eps_r * ya[1] \
        #         + self.kappa_debye * C.EPS_R_WATER * C.N_SITES_SILICA / self.n_max \
        #         * k_fraction(C.K_SILICA_A, C.K_SILICA_B, c_bulk_arr[0] * np.exp(-ya[0]))
        # else:
        #     left = - 2 * eps_r * ya[1] \
        #         + self.kappa_debye * C.EPS_R_WATER * C.N_SITES_SILICA / self.n_max \
        #         * k_fraction(C.K_WATER/C.K_SILICA_A, C.K_WATER/C.K_SILICA_B, c_bulk_arr[1] * np.exp(ya[0]))
        right = yb[0]

        return np.array([left.squeeze(), right])

    def insulator_sequential_solve(self,
                         ph_range: np.ndarray,
                         tol: float=1e-3):
        """
        Sweep over a boundary condition parameter array (potential, pH) and use the previous
        solution as initial condition for the next. The initial condition assumes that we
        start at the PZC.

        Returns: charge for each parameter; list of SpatialProfilesSolutions
        """
        chg = np.zeros(ph_range.shape)
        phi = np.zeros(ph_range.shape)
        profile_list = []
        max_res = np.zeros(ph_range.shape)

        x_axis = self.create_x_mesh(100, 1000)
        y_initial = np.zeros((2, x_axis.shape[0]))

        for i, p_h in enumerate(ph_range):
            sol = solve_bvp(
                self.ode_lambda(p_h),
                self.insulator_bc_lambda(p_h),
                x_axis,
                y_initial,
                tol=tol,
                max_nodes=int(1e8),
                verbose=0)
            prf = self.compute_profiles(sol, p_h)
            chg[i] = prf.efield[0] * C.EPS_0 * prf.eps[0]
            phi[i] = prf.phi[0]
            max_res[i] = np.max(sol.rms_residuals)
            profile_list.append(prf)

            x_axis = sol.x
            y_initial = sol.y

        print(f"Sweep from pH {ph_range[0]:.2f} to {ph_range[-1]:.2f}. " \
            + f"Maximum relative residual: {np.max(max_res):.5e}.")
        return chg, phi, profile_list

    def ph_sweep(self, ph_range: np.ndarray, tol: float=1e-3):
        """
        Numerical solution to a potential sweep for a defined double-layer model.
        """
        # Find pH closest to PZC
        ph_pzc = -1/2 * np.log10(C.K_SILICA_A*C.K_SILICA_B)
        i_pzc = np.argmin(np.abs(ph_range - ph_pzc)).squeeze()

        chg = np.zeros(ph_range.shape)
        phi = np.zeros(ph_range.shape)

        chg_neg, phi_neg, profiles_neg = self.insulator_sequential_solve(
            ph_range[i_pzc::-1],
            tol)
        chg[:i_pzc+1] = chg_neg[::-1]
        phi[:i_pzc+1] = phi_neg[::-1]
        chg[i_pzc:], phi[i_pzc:], profiles_pos = self.insulator_sequential_solve(
            ph_range[i_pzc::1],
            tol)
        cap = np.gradient(chg, edge_order=2)/np.gradient(phi) * 1e2

        sol = PotentialSweepSolution(phi=phi,
                                     charge=chg,
                                     cap=cap,
                                     profiles=profiles_neg[::-1] + profiles_pos,
                                     name=self.name)
        return sol

    def insulator_spatial_profiles(self, p_h: float, tol: float=1e-3):
        """
        Get spatial profiles solution struct.
        """
        ph_pzc = -1/2 * np.log10(C.K_SILICA_A*C.K_SILICA_B)
        sign = (p_h - ph_pzc)/abs(p_h - ph_pzc)
        _, _, profiles = self.insulator_sequential_solve(
            np.arange(ph_pzc, p_h, sign*0.01),
            tol)
        return profiles[-1]
