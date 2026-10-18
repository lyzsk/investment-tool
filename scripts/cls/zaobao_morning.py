# 兼容垫片(10/15): 已更名为 distill_cls_zaobao.py; Java ClsZaobaoHandler 改了路径, 但要重启应用才生效——重启前 07:00 定时仍调本文件。
# 用户重启应用后删除本文件。
import runpy, sys
from pathlib import Path
sys.argv[0] = str(Path(__file__).with_name("distill_cls_zaobao.py"))
runpy.run_path(sys.argv[0], run_name="__main__")
