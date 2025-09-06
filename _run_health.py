import sys
sys.path.append('.')
from part3_health import health_check
import builtins
builtins.input = lambda *a, **k: 'n'
health_check()
print('health_check ran')
