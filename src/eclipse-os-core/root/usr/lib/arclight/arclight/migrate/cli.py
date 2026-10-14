"""arclight-migrate: record, plan, export and import a system without touching the source."""
import argparse
import os
import sys


def cmd_manifest(a):
    from . import manifest
    def progress(name):
        print(f"  probing {name} ...", file=sys.stderr, flush=True)
    data = manifest.collect(progress=None if a.quiet else progress, skip=set(a.skip or []))
    out = manifest.write(data, a.out)
    errs = data.get("errors") or {}
    print(f"manifest written to {out}/ ({len(errs)} probe errors)")
    for k, v in errs.items():
        print(f"  ! {k}: {v}", file=sys.stderr)
    return 0


def cmd_plan(a):
    import shutil
    from . import plan as mplan
    free = a.free_gib * 1024 ** 3 if a.free_gib else shutil.disk_usage(a.into if os.path.exists(a.into) else os.path.dirname(a.into.rstrip("/")) or "/").free
    p = mplan.build(a.home, a.into, free, can_share=a.share,
                    progress=None if a.quiet else (lambda r: print(f"  measuring ~/{r}", file=sys.stderr)))
    print(p.to_json())
    print(p.summary(), file=sys.stderr)
    return 0 if p.fits() else 3


def cmd_copy(a):
    import json
    import time
    from . import plan as mplan, copy as mcopy
    p = mplan.Plan.from_json(open(a.plan).read())
    src, dst = p.source_home, a.into or p.target_home
    os.makedirs(dst, exist_ok=True)
    st = os.stat(src)
    os.chown(dst, st.st_uid, st.st_gid)
    copies = [i for i in p.items if i.action == "copy"]
    for n, it in enumerate(copies, 1):
        print(f"[{n}/{len(copies)}] copy ~/{it.path}", file=sys.stderr)
        mcopy.copy_item(src, dst, it.path)
    bad = {}
    for it in copies:
        d = mcopy.verify_item(src, dst, it.path)
        if d:
            bad[it.path] = d[:5]
    rep = {"time": time.time(), "source": src, "target": dst, "copied": [i.path for i in copies],
           "shared": [i.path for i in p.items if i.action == "share"], "skipped": [i.path for i in p.items if i.action == "skip"],
           "verified": not bad, "differences": bad}
    if a.report:
        os.makedirs(os.path.dirname(a.report), exist_ok=True)
        open(a.report, "w").write(json.dumps(rep, indent=2))
    print(("verified: every copied file is identical" if not bad else f"VERIFY FAILED: {list(bad)[:5]}"), file=sys.stderr)
    if rep["shared"]:
        print("shared (not copied): " + ", ".join(rep["shared"]) + "  -> add bind mounts for these, see the guide",
              file=sys.stderr)
    return 0 if not bad else 4


def cmd_export(a):
    from . import plan as mplan, copy as mcopy
    p = mplan.Plan.from_json(open(a.plan).read())
    r = mcopy.export_bundle(p.source_home, p, a.to)
    print(f"bundle written and read back: {r}")
    return 0


def cmd_import(a):
    from . import copy as mcopy
    mcopy.import_bundle(a.bundle, a.into)
    print("bundle imported; every file checksum verified")
    return 0


def cmd_fingerprint(a):
    import json
    from . import copy as mcopy
    print(json.dumps(mcopy.fingerprint(a.root, exclude=a.exclude or [])))
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(prog="arclight-migrate", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)
    m = sub.add_parser("manifest", help="export an exact record of this system (read-only, no root)")
    m.add_argument("--out", default="arclight-manifest", help="output directory")
    m.add_argument("--skip", action="append", help="skip a probe (e.g. home)")
    m.add_argument("-q", "--quiet", action="store_true")
    m.set_defaults(fn=cmd_manifest)
    pl = sub.add_parser("plan", help="classify a home into copy / share / skip with sizes (JSON on stdout)")
    pl.add_argument("--home", required=True, help="the home to migrate (e.g. /old/home/alex, mounted read-only)")
    pl.add_argument("--into", required=True, help="where it goes (e.g. /mnt/home/alex)")
    pl.add_argument("--free-gib", type=int, help="free space to plan for (default: measured at --into)")
    pl.add_argument("--no-share", dest="share", action="store_false", help="the old disk will not stay (no shared items)")
    pl.add_argument("-q", "--quiet", action="store_true")
    pl.set_defaults(fn=cmd_plan)
    cp = sub.add_parser("copy", help="copy the plan's COPY items, then verify every file by checksum")
    cp.add_argument("plan")
    cp.add_argument("--into", help="override the plan's target home")
    cp.add_argument("--report", help="write a JSON report (the Rite reads /mnt/var/lib/arclight/migration-report.json)")
    cp.set_defaults(fn=cmd_copy)
    ex = sub.add_parser("export", help="write a verified bundle (for installing over the same disk)")
    ex.add_argument("plan")
    ex.add_argument("--to", required=True)
    ex.set_defaults(fn=cmd_export)
    im = sub.add_parser("import", help="unpack a bundle into a new home and verify every file")
    im.add_argument("bundle")
    im.add_argument("--into", required=True)
    im.set_defaults(fn=cmd_import)
    fp = sub.add_parser("fingerprint", help="metadata fingerprint of a tree (proves it was not changed)")
    fp.add_argument("root")
    fp.add_argument("--exclude", action="append")
    fp.set_defaults(fn=cmd_fingerprint)
    a = p.parse_args(argv)
    return a.fn(a)
