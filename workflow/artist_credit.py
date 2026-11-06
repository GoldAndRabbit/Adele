"""Consistent list separators for display artist credits."""
import re


def artist_credit(names):
    return re.sub(r"\s*(?:[、，,&]|与)\s*", " & ", names).strip()
