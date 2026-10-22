# -*- coding: utf-8 -*-
"""ipv4_first.py — 让 urllib / socket 解析域名时 IPv4 地址排在前面(10/21 查明: 本机 IPv6 出口不通, Python 先试 IPv6 要等几秒才回落,
3 秒盘口实际变成约 9 秒一张、单次请求 9~40 秒; curl 走 IPv4 只要 0.1 秒)。import 即生效, 只调整顺序不删 IPv6(IPv6 修好后自然可用)"""
import socket

_orig = socket.getaddrinfo


def _v4_first(*a, **k):
    r = _orig(*a, **k)
    return sorted(r, key=lambda x: 0 if x[0] == socket.AF_INET else 1)


if getattr(socket.getaddrinfo, "__name__", "") != "_v4_first":
    socket.getaddrinfo = _v4_first
