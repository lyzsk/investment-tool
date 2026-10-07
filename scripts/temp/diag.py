import subprocess, csv, io
out = subprocess.run(["tasklist","/FO","CSV"], capture_output=True, text=True).stdout
rows = list(csv.DictReader(io.StringIO(out)))
py = [r for r in rows if r["Image Name"].startswith("python")]
py.sort(key=lambda r: int(r["Mem Usage"].replace(",","").split()[0]), reverse=True)
print("python 进程(按内存):")
for r in py[:6]: print(f'  PID {r["PID"]}: {r["Mem Usage"]}')
