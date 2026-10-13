"""eclipse-ai: the Eclipse AI window, or its terminal modes (based on Arch AI by Arthur).

  eclipse-ai                                 open the window (or focus it: single instance)
  eclipse-ai --send TEXT                     open it and send TEXT
  eclipse-ai --work-for 45m GOAL             timed autonomous run in this terminal (--gui: in the window)
  eclipse-ai --root-queue / --clear-root-queue / --run-root-queue / --runs
"""
import sys

_HEADLESS = {"--work-for", "--root-queue", "--clear-root-queue", "--run-root-queue", "--runs", "--help", "-h"}


def _name_process():
    """Show up as `eclipse-ai` (not python3): the model server's idle watchdog and arclightd's action log
    (which agent did it) look for that name."""
    try:
        import ctypes
        ctypes.CDLL(None).prctl(15, b"eclipse-ai", 0, 0, 0)   # PR_SET_NAME
    except Exception:
        pass


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    _name_process()
    if _HEADLESS & set(argv) and "--gui" not in argv:
        if "--help" in argv or "-h" in argv:
            print(__doc__.strip())
            return 0
        from . import cli
        return cli.main(argv)
    from . import ui
    return ui.main()
