#!/usr/bin/env python3
from __future__ import annotations

from abc import ABCMeta
from typing import TypeVar

from attrs import define, evolve
from cattrs.preconf.json import make_converter

__all__ = [
    "BaseEntity",
    "json_converter",
]

T = TypeVar("T")


@define
class BaseEntity(metaclass=ABCMeta):
    def __copy__(self):
        return evolve(self)

    def copy(self, **changes):
        return evolve(self, **changes)


json_converter = make_converter(omit_if_default=True)
