# -*- coding: utf-8 -*-
"""10/26 晚用户令: hermes 主模型 glm-5.3 盘中偶发 429(code 1305 "该模型当前访问量过大" = 智谱服务端拥堵, 不是我们的额度)
→ 用 hermes 自带 fallback_providers: glm 重试 3 次仍 429 → 这一轮自动换 kimi-k3, 下一条消息再先试 glm(按轮切, 不用定时切)。
只走 hermes 官方 API(load_config / save_config / save_env_value), 不手改 yaml; key 从 key-switcher 的 keyFile 读, 不打印。
用法: <hermes venv python> add_fallback_k3.py"""
import json
import os
import sys
from pathlib import Path

H = Path(os.environ.get("LOCALAPPDATA", "")) / "hermes" / "hermes-agent"
sys.path.insert(0, str(H))
from hermes_cli.config import load_config, save_config, save_env_value  # noqa: E402

KS = Path(r"C:/Users/admin/dev/dev-notes/others/key-switcher")
prof = json.loads((KS / "profiles-hermes.json").read_text(encoding="utf-8"))
prof = prof.get("profiles", prof)["kimi-code-k3"]
kf = None
d = KS.parent
for _ in range(5):
    if (d / prof["keyFile"]).exists():
        kf = d / prof["keyFile"]
        break
    d = d.parent
if not kf:
    sys.exit("找不到 keyFile")
save_env_value("HERMES_FB_KIMI_K3_KEY", kf.read_text(encoding="utf-8").strip())
cfg = load_config()
cfg["fallback_providers"] = [{"provider": "custom", "model": prof["model"], "base_url": prof["base_url"], "key_env": "HERMES_FB_KIMI_K3_KEY"}]
save_config(cfg)
print("ok: fallback_providers =", [{k: v for k, v in e.items()} for e in cfg["fallback_providers"]])
