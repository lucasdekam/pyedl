"""
Modelling the double layer using the Gongadze-Iglic approach.
"""

from typing import Optional
import numpy as np
from numpy import newaxis
from scipy import constants

from bvpsweep import sweep_solve_bvp

from . import langevin as L
from .electrolyte import LatticeElectrolyte


class GongadzeIglic:
    """
    A class to model the electric double layer with the approach of Gongadze and Iglic.

    Parameters:
        electrolyte (LatticeElectrolyte): The electrolyte model.
        temperature (float, optional): Temperature in Kelvin. Default is 298 K.
        ohp (float, optional): Outer Helmholtz plane distance.
        eps_stern (float, optional): Stern layer permittivity.

    Attributes:
        el (LatticeElectrolyte): The electrolyte model.
        ohp (float, optional): Outer Helmholtz plane distance.
        eps_stern (float, optional): Stern layer permittivity.
        kappa (float): Parameter resulting from the nondimensionalization procedure.
        kbt_ev (float): Thermal energy in electronvolts.

    Methods:
        densities(y: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
            Compute the density profiles of all species.
        ode_rhs(x: np.ndarray, y: np.ndarray) -> np.ndarray:
            Compute the right-hand side of the differential equation for the ODE solver.
        boundary_condition(ya: np.ndarray, yb: np.ndarray, y0: float) -> np.ndarray:
            Apply the Stern layer boundary condition.
        permittivity(y: np.ndarray) -> np.ndarray:
            Compute the relative permittivity.
        voltammetry(x_mesh: np.ndarray, potential: np.ndarray, tol: float = 1e-3) -> np.ndarray:
            Perform a numerical solution to a potential sweep for the defined double-layer model.
    """

    def __init__(
        self,
        electrolyte: LatticeElectrolyte,
        temperature: float = 298,
        ohp: Optional[float] = None,
        eps_stern: Optional[float] = None,
    ) -> None:
        self.el = electrolyte
        self.ohp = ohp
        self.eps_stern = eps_stern
        kbt = constants.Boltzmann * temperature
        self.kappa = (
            constants.elementary_charge**2
            / constants.epsilon_0
            / constants.angstrom
            / kbt
        )
        self.kbt_ev = kbt / constants.elementary_charge

    def densities(self, y: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """
        Calculate the ion and solvent densities based on the provided potential array.

        Parameters:
            y (np.ndarray): A 2D array where the first row represents the dimensionless
                           electric potential and the second row represents the dimensionless
                           derivative of the potential (-electric field).

        Returns:
            tuple: A tuple containing two ndarrays:
                - ion_densities (np.ndarray): The calculated ion densities.
                - sol_densities (np.ndarray): The calculated solvent densities.
        """
        ion_boltzmann_fac = np.exp(-self.el.ion_q[:, newaxis] * y[0, :])
        sol_boltzmann_fac = L.sinh_x_over_x(self.el.sol_p[:, newaxis] * y[1, :])
        denom = np.sum(
            self.el.ion_f_b[:, newaxis] * ion_boltzmann_fac, axis=0
        ) + np.sum(self.el.sol_f_b[:, newaxis] * sol_boltzmann_fac, axis=0)
        ion_densities = self.el.ion_n_b[:, newaxis] * ion_boltzmann_fac / denom
        sol_densities = self.el.sol_n_b[:, newaxis] * sol_boltzmann_fac / denom
        return ion_densities, sol_densities

    def ode_rhs(
        self, x: np.ndarray, y: np.ndarray  # pylint: disable=unused-argument
    ) -> np.ndarray:
        """
        Compute the right-hand side of the differential equation for the ODE solver.

        Parameters:
            x (np.ndarray): Independent variable (not used in the computation).
            y (np.ndarray): Dependent variable, where y[0, :] represents the function values
                            and y[1, :] represents the derivatives.

        Returns:
            np.ndarray: A 2D array where the first row contains the derivatives of y[0, :]
                        and the second row contains the derivative of y[1, :].
        """
        dy0 = y[1, :]
        ion_densities, sol_densities = self.densities(y)
        ion_f = self.el.ion_sizes[:, newaxis] * ion_densities / self.el.n_site
        sol_f = self.el.sol_sizes[:, newaxis] * sol_densities / self.el.n_site
        f_1 = np.sum(self.el.ion_q[:, newaxis] * ion_densities, axis=0)
        f_2 = np.sum(
            self.el.sol_p[:, newaxis]
            * y[1, :]
            * sol_densities
            * L.langevin_x(self.el.sol_p[:, newaxis] * y[1, :])
            * np.sum(self.el.ion_q[:, newaxis] * ion_f, axis=0),
            axis=0,
        )
        g_1 = np.sum(
            self.el.sol_p[:, newaxis] ** 2
            * sol_densities
            * L.d_langevin_x(self.el.sol_p[:, newaxis] * y[1, :]),
            axis=0,
        )
        g_2 = np.sum(
            self.el.sol_p[:, newaxis] ** 2
            * sol_densities
            * L.langevin_x(self.el.sol_p[:, newaxis] * y[1, :]) ** 2
            * (1 - np.sum(sol_f, axis=0)),
            axis=0,
        )

        dy1 = (
            -self.kappa
            * (f_1 + f_2)
            / (self.el.min_eps + self.kappa * g_1 + self.kappa * g_2)
        )
        return np.vstack([dy0, dy1])

    def boundary_condition(
        self, ya: np.ndarray, yb: np.ndarray, y0: float
    ) -> np.ndarray:
        """
        Apply the Stern layer boundary condition.

        Parameters:
            ya (np.ndarray): The solution vector at the left of the interval (outer Helmholtz plane).
            yb (np.ndarray): The solution vector at the right of the interval (electrolyte bulk).
            y0 (float): The value of the dimensionless potential at the electrode.

        Returns:
            np.ndarray: An array containing the boundary condition residuals.
        """
        ohp = self.ohp if self.ohp else self.el.ohp(y0)
        eps_ratio = (
            self.permittivity(ya.reshape(2, 1)).squeeze() / self.eps_stern
            if self.eps_stern
            else 1
        )
        return np.array(
            [
                ya[0] - y0 - ya[1] * ohp * eps_ratio,
                yb[0],
            ]
        )

    def permittivity(self, y: np.ndarray) -> np.ndarray:
        """
        Compute the relative permittivity according to the Gongadze-Iglic model.

        Parameters:
            y (np.ndarray): A 2D array where the first row represents the dimensionless
                            potential and the second row represents the dimensionless derivative
                            of the potential. The columns represent different points in space.

        Returns:
            np.ndarray: The computed relative permittivity at each point in space.
        """
        _, sol_densities = self.densities(y)
        return self.el.min_eps + self.kappa * np.sum(
            self.el.sol_p**2
            * sol_densities
            * L.langevin_x_over_x(self.el.sol_p[:, newaxis] * y[1, :]),
            axis=0,
        )

    def voltammetry(
        self, x_mesh: np.ndarray, potential: np.ndarray, tol: float = 1e-3
    ) -> np.ndarray:
        """
        Perform a numerical solution to a potential sweep for the defined double-layer model.

        Parameters:
            x_mesh (np.ndarray): Spatial mesh points.
            potential (np.ndarray): Applied potential array.
            tol (float, optional): Tolerance for the solver. Default is 1e-3.

        Returns:
            np.ndarray: The computed current density array.
        """
        y0 = np.zeros((2, len(x_mesh)))

        y = sweep_solve_bvp(
            fun=self.ode_rhs,
            bc=self.boundary_condition,
            x0=x_mesh,
            y0=y0,
            sweep_par=potential / self.kbt_ev,
            sweep_par_start=0.0,
            tol=tol,
        )

        return (
            -constants.epsilon_0
            * self.permittivity(y[:, :, 0])
            * y[1, :, 0]
            * self.kbt_ev
            / constants.angstrom
        )