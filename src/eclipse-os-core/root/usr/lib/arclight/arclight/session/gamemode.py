"""Game mode grew into Totality (session/totality.py): `arc game mode` and the game.mode API are kept as
aliases so old scripts, routines and the AI keep working."""
from . import totality


def status():
    return totality.status()


def on():
    return totality.on()


def off():
    return totality.off()


def mode(action="toggle"):
    """Game mode = Totality: action = on | off | toggle | status."""
    return totality.mode(action)
