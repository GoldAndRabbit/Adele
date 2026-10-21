# -*- coding: utf-8 -*-
import subprocess


def run(cmd, cwd=None, env=None, check=True):
    print("\n$ " + " ".join(f'"{x}"' if " " in str(x) else str(x) for x in cmd), flush=True)
    return subprocess.run([str(x) for x in cmd], check=check, cwd=cwd, env=env)


def hms(t):
    t = max(0.0, float(t))
    return f"{int(t // 3600)}:{int(t % 3600 // 60):02d}:{t % 60:04.1f}"
