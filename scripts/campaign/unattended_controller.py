"""Durable single-controller loop for the Professionalize-only portfolio campaign."""
from __future__ import annotations
import argparse, json, os, signal, subprocess, sys, time, uuid
from datetime import datetime, timezone
from pathlib import Path
from src.utils.atomic_write import atomic_write
from src.workers.campaign_manifest import CampaignManifest

def boot_id() -> str:
    import psutil
    return f"{int(psutil.boot_time())}"

class Controller:
    def __init__(self, args):
        self.a=args; self.stop=False; self.child=None; self.session=str(uuid.uuid4())
        self.root=args.ledger_root / CampaignManifest.load(args.manifest).campaign_id
        self.state=self.root / "controller_state.json"; self.root.mkdir(parents=True,exist_ok=True)
    def write(self,status,reason=None,**extra):
        payload={"schema":1,"status":status,"reason":reason,"session_id":self.session,
                 "pid":os.getpid(),"boot_id":boot_id(),"updated_at":time.time(),**extra}
        atomic_write(self.state,json.dumps(payload,indent=2,sort_keys=True),fsync=True,create_parents=True)
    def on_signal(self,signum,_frame):
        self.stop=True; self.write("STOPPING",f"signal_{signum}")
        if self.child and self.child.poll() is None: self.child.terminate()
    def run(self):
        for sig in (signal.SIGINT,signal.SIGTERM): signal.signal(sig,self.on_signal)
        self.write("STARTING")
        merge=[sys.executable,str(self.a.runtime/"scripts/campaign/merge_campaign_journals.py"),"--campaign-id",self.root.name,"--ledger-root",str(self.a.ledger_root)]
        while not self.stop:
            subprocess.run(merge,check=True,timeout=300)
            cmd=[sys.executable,"-u",str(self.a.runtime/"scripts/campaign/launch_parallel_campaign_shards.py"),
                 "--campaign-manifest",str(self.a.manifest),"--ledger-root",str(self.a.ledger_root),"--child","gate5",
                 "--max-workers","8","--wait","--device","cpu","--no-force-serialize","--checkpoint-wave-shards","64",
                 "--tm-repository-root",str(self.a.control),"--tm-intent-spool-path",str(self.a.spool),
                 "--session-id",self.session,"--watchdog-state",str(self.root/"watchdog_state.json")]
            if self.a.release: cmd += ["--throughput-release",str(self.a.release)]
            self.write("RUNNING",command="bounded_wave")
            self.child=subprocess.Popen(cmd,cwd=self.a.control)
            code=self.child.wait(); self.child=None
            if self.stop: self.write("INTERRUPTED","controller_signal"); return 130
            if code: self.write("RETRY_WAIT",f"wave_exit_{code}"); time.sleep(self.a.retry_seconds); continue
            progress=subprocess.check_output([sys.executable,str(self.a.runtime/"scripts/campaign/campaign_progress.py"),"--manifest",str(self.a.manifest),"--ledger-root",str(self.a.ledger_root),"--spool",str(self.a.spool)],cwd=self.a.control,text=True)
            remaining=int(json.loads(progress)["remaining"])
            self.write("RUNNING",remaining=remaining)
            if remaining==0: self.write("COMPLETE",remaining=0); return 0
        return 130

def main():
    p=argparse.ArgumentParser(); p.add_argument("--manifest",type=Path,required=True);p.add_argument("--runtime",type=Path,required=True);p.add_argument("--control",type=Path,required=True);p.add_argument("--ledger-root",type=Path,required=True);p.add_argument("--spool",type=Path,required=True);p.add_argument("--release",type=Path);p.add_argument("--retry-seconds",type=int,default=120)
    a=p.parse_args(); a.manifest=a.manifest.resolve();a.runtime=a.runtime.resolve();a.control=a.control.resolve();a.ledger_root=a.ledger_root.resolve();a.spool=a.spool.resolve()
    try: return Controller(a).run()
    except BaseException as e:
        try: Controller(a).write("FAILED",f"{type(e).__name__}: {e}"[:500])
        except Exception: pass
        raise
if __name__=="__main__": raise SystemExit(main())
