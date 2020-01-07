from copy import deepcopy

from fireant.utils import immutable
from pypika import NullValue


class Modifier:
    wrapped_key = "wrapped"

    def __init__(self, wrapped):
        wrapped_key = super().__getattribute__("wrapped_key")
        setattr(self, wrapped_key, wrapped)

    def __copy__(self):
        cls = self.__class__
        result = cls.__new__(cls)
        result.__dict__.update(self.__dict__)
        return result

    def __deepcopy__(self, memo):
        cls = self.__class__
        result = cls.__new__(cls)
        memo[id(self)] = result
        for k, v in self.__dict__.items():
            setattr(result, k, deepcopy(v, memo))
        return result

    def __getattr__(self, attr):
        if attr in self.__dict__:
            return super().__getattribute__(attr)

        wrapped_key = super().__getattribute__("wrapped_key")
        wrapped = super().__getattribute__(wrapped_key)
        return getattr(wrapped, attr)

    def __setattr__(self, attr, value):
        wrapped_key = super().__getattribute__("wrapped_key")
        if attr == wrapped_key:
            super().__setattr__(attr, value)
            return

        wrapped = super().__getattribute__(wrapped_key)

        if attr in wrapped.__dict__:
            setattr(wrapped, attr, value)
            return

        super().__setattr__(attr, value)

    def __hash__(self):
        return hash(repr(self))

    def __repr__(self):
        wrapped_key = super().__getattribute__("wrapped_key")
        wrapped = super().__getattribute__(wrapped_key)
        return "{}({})".format(self.__class__.__name__, repr(wrapped))

    @immutable
    def for_(self, wrapped):
        wrapped_key = super().__getattribute__("wrapped_key")
        setattr(self, wrapped_key, wrapped)


class DimensionModifier(Modifier):
    wrapped_key = "dimension"


class FilterModifier(Modifier):
    wrapped_key = "filter"


class Rollup(DimensionModifier):
    @property
    def definition(self):
        return NullValue()


class OmitFromRollup(FilterModifier):
    pass
