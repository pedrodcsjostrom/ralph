"""Ralph implements a spec unattended, one ticket at a time, on one integration branch."""

import os

# The clone ralph runs from: this package is src/ralph in it, next to bin/, plugin/ and wrapper/.
CLONE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
