# -*- coding: utf-8 -*-
"""券商交割单共享解析：兼容流水号前缀与证券买入/卖出。"""
import re


def parse_trade_line(line):
    m = re.match(r"(?:\d+:)?(\d\d:\d\d:\d\d)\s+(\d{6})\s+(\S+)\s+证券(买入|卖出)\s+(\d+)\s+([\d.]+)", line.strip())
    if not m or m.group(2) == "204001":
        return None
    tm, code, name, side, qty, px = m.groups()
    return tm, code, name, "BUY" if side == "买入" else "SELL", float(px), int(qty)
