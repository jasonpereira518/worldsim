import importlib

from .base import Module  # noqa: F401

REGISTRY = {'epidemiology': ('epidemiology', 'Epidemiology'), 'disaster': ('disaster', 'Earthquake'), 'launch': ('launch', 'Launch'),
            'trade': ('trade', 'Trade'), 'generic': ('generic', 'Generic')}


def get(name: str):
    mod, cls = REGISTRY[name]
    return getattr(importlib.import_module(f'{__name__}.{mod}'), cls)()
