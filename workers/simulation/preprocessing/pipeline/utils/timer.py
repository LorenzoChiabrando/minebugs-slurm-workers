import time
import os
import json
from collections import OrderedDict
from typing import Optional

class SectionTimer:
    """
    Lightweight timing helper context manager.
    
    Usage:
        timer = SectionTimer(enabled=True, outdir="./output")
        with timer("phase_name"):
            do_something()
        timer.finish_and_dump()
    """
    def __init__(self, enabled: bool = False, outdir: Optional[str] = None):
        self.enabled = enabled
        self.outdir = outdir or "."
        self.timings = OrderedDict()      
        self._t0_global = time.perf_counter()

    def __call__(self, name: str):
        class _Ctx:
            def __init__(_self, outer, nm):
                _self.outer = outer
                _self.nm = nm
            def __enter__(_self):
                _self.t0 = time.perf_counter()
                return _self
            def __exit__(_self, exc_type, exc, tb):
                dt = time.perf_counter() - _self.t0
                _self.outer.timings[_self.nm] = _self.outer.timings.get(_self.nm, 0.0) + dt
                if _self.outer.enabled:
                    print(f"[TIME] {_self.nm}: {dt:.3f}s")
        return _Ctx(self, name)

    def _paths(self):
        os.makedirs(self.outdir, exist_ok=True)
        return (
            os.path.join(self.outdir, "timings.txt"),
            os.path.join(self.outdir, "timings.json"),
        )

    def finish_and_dump(self):
        total_wall = time.perf_counter() - self._t0_global
        sum_phases = sum(self.timings.values())
        self.timings["TOTAL_PHASES_SUM"] = sum_phases
        self.timings["TOTAL_WALL"] = total_wall

        if self.enabled:
            path_txt, path_json = self._paths()
            with open(path_txt, "w") as f:
                for k, v in self.timings.items():
                    f.write(f"{k}\t{v:.6f}\n")
            with open(path_json, "w") as f:
                json.dump(self.timings, f, indent=2)
            print(f"[OK] Timings written to: {path_txt} and {path_json}")
