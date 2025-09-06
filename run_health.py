import sys
sys.path.append('.')
import part1_bootstrap
part1_bootstrap.DEBUG = True
import part3_health
# Auto-answer 'n' to final prompt so it doesn't block
import builtins
builtins.input = lambda *a, **k: 'n'
print('Running health_check (non-interactive test)...')
part3_health.health_check()
print('health_check finished')