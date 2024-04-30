import numpy as np

t = np.linspace(0, 5, 6)
turn_on = np.maximum(0.7, (1.0 - (t / 5) * 0.3))

print(f"turn_on 0-5: {turn_on}")

t = np.linspace(6, 59, 54)
turn_on = np.minimum(0.975, (0.6 + (t / 45) * 0.375))

print(f"turn_on 6-59: {turn_on}")

t = np.linspace(0, 59, 60)

turn_off = np.maximum(1, (1.3 - ((t / 45) * 0.3)))

print(f"turn_off 0-59: {turn_off}")
