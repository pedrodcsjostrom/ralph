import os
import sys

# The package lives in src/, as bin/ralph finds it; tests that import it directly need it on the path too.
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))
