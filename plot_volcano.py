"""
Making volcano plots
"""

import numpy as np 
import matplotlib.pyplot as plt

from edl import models
from edl import constants as C

# log [Cat], log |j|, phi vs. RHE, gamma, pH
data = [
    (-2.2232145886032364, -3.9409092143350355, -0.65, 7, 11),
    (-1.28571446087898, -3.6477271982460993, -0.65, 7, 11),
    (-0.5178566684527628, -3.402272661303688, -0.65, 7, 11),
    (-0.008928027688166473, -3.22499999219721, -0.65, 7, 11),
    (-2.2232145886032364, -4.165909206532246, -0.60, 7, 11),
    (-1.2946424885671461, -3.8931817351885107, -0.60, 7, 11),
    (-0.5178566684527628, -3.7022727549371632, -0.60, 7, 11),
    (0, -3.5249999297748937, -0.60, 7, 11),
    (-2.2232145886032364, -4.384090809073333, -0.55, 7, 11),
    (-1.28571446087898, -4.104545572296643, -0.55, 7, 11),
    (-0.5178566684527628, -4.002272848570638, -0.55, 7, 11),
    (0, -3.7977274011186286, -0.55, 7, 11),
    (-2.2232145886032364, -4.547727167034941, -0.50, 7, 11),
    (-1.28571446087898, -4.26818193025825, -0.50, 7, 11),
    (-0.5178566684527628, -4.172727284076785, -0.50, 7, 11),
    (0, -4.029545470860378, -0.50, 7, 11),
    (-0.9863013698630138, -3.1702127115604553, -0.60, 7, 13),
    (-0.8264841576145121, -3.1382979422794146, -0.60, 7, 13),
    (-0.22374443158711455, -2.9946809326593167, -0.60, 7, 13),
    (0.041095890410959734, -2.8750000913092357, -0.60, 7, 13),
    (-0.9771690891213609, -3.489361865318634, -0.55, 7, 13),
    (-0.8264841576145121, -3.481382899070667, -0.55, 7, 13),
    (-0.22374443158711455, -3.32180868742852, -0.55, 7, 13),
    (0.045661821757278176, -3.226064014348455, -0.55, 7, 13),
    (0.045661821757278176, -3.521276634599675, -0.50, 7, 13),
    (-0.22374443158711455, -3.6409574759497563, -0.50, 7, 13),
    (-0.8264841576145121, -3.7845744855698538, -0.50, 7, 13),
    (-0.9817354385166949, -3.7925530865808783, -0.50, 7, 13),
    (-0.9908677192583476, -4.031914769281041, -0.45, 7, 13),
    (-0.8264841576145121, -4.055850937551057, -0.45, 7, 13),
    (-0.22374443158711455, -3.89627672590891, -0.45, 7, 13),
    (0.041095890410959734, -3.776595884558829, -0.45, 7, 13),
    (-2.2191779756751933, -4.343891339731531, -0.65, 6, 11),
    (-1.5945205067129782, -3.844343759437493, -0.65, 6, 11),
    (-1.2986301266782445, -3.5909502802301168, -0.65, 6, 11),
    (-0.9972601279417976, -3.359275929622865, -0.65, 6, 11),
    (-2.224657594376907, -4.474208099808236, -0.60, 6, 11),
    (-1.5890408880112648, -4.003620020473017, -0.60, 6, 11),
    (-1.2876713909335837, -3.735746459373572, -0.60, 6, 11),
    (-0.9972601279417976, -3.5040724401789793, -0.60, 6, 11),
    (-2.224657594376907, -4.655203820856544, -0.55, 6, 11),
    (-1.5835617709683174, -4.199095160588075, -0.55, 6, 11),
    (-1.2986301266782445, -4.003620020473017, -0.55, 6, 11),
    (-0.9972601279417976, -3.721267040306822, -0.55, 6, 11),
    (-2.2191779756751933, -4.865158380038353, -0.50, 6, 11),
    (-1.5890408880112648, -4.401810341649167, -0.50, 6, 11),
    (-1.2931505079765313, -4.199095160588075, -0.50, 6, 11),
    (-1.002739746643511, -3.93122159948863, -0.50, 6, 11),
]

# currents = [10**point[1] for point in data]
currents = [point[1] for point in data]
efield = []

for point in data:
    model = models.AqueousVariableStern(10**point[0], point[3], 2, 4, 1)
    sol = model.spatial_profiles(
        phi0=point[2] - C.AU_PZC_SHE_V - 59e-3 * point[4], 
        p_h=point[4],
        tol=1e-4)
    efield.append(sol['efield'].values[0] * 1e-9)

fig = plt.figure(figsize=(5,4))
ax1 = fig.add_subplot()

ax1.plot(efield, currents, '.')

plt.show()