import subprocess, pathlib
d = pathlib.Path(r'C:/Users/admin/dev/investment-tool/scripts/plan-a/backtest/runs/live-20260928')
prompt = (d/'prompt.txt').read_text(encoding='utf-8')
print('prompt chars:', len(prompt))
r = subprocess.run('claude -p --dangerously-skip-permissions', input=prompt, shell=True,
    capture_output=True, timeout=900, encoding='utf-8', cwd=r'C:/Users/admin/dev/investment-tool')
(d/'chain_output.md').write_text(r.stdout or '', encoding='utf-8')
(d/'chain_stderr.txt').write_text(r.stderr or '', encoding='utf-8')
print('RC', r.returncode, 'OUTLEN', len(r.stdout or ''), 'ERRLEN', len(r.stderr or ''))
