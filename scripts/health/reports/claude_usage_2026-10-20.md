# claude -p 用量 2026-10-20(官方价, 实付按 key 系数折算)

会话 310 个, 合计 $264.3; 超线会话 11 个(写缓存>300k 或 读缓存>5M)

| 类别 | 会话数 | 均写缓存(k) | 均读缓存(k) | 均输出(k) | 合计$ |
|---|---|---|---|---|---|
| chain-盘中 | 102 | 103 | 831 | 16.2 | 109.1 |
| chain-0915 | 166 | 49 | 163 | 6.5 | 73.7 |
| bili-md-batch | 14 | 161 | 3161 | 43.9 | 38.2 |
| bili-distill-batch | 11 | 155 | 3889 | 49.0 | 27.8 |
| tzzb-distill-daily | 2 | 249 | 10141 | 65.8 | 9.2 |
| profile-index | 7 | 40 | 0 | 9.2 | 2.7 |
| checkmd-tzzb-spec | 3 | 53 | 874 | 14.8 | 2.2 |
| checkmd-cls | 1 | 83 | 917 | 6.9 | 0.7 |
| t-swing | 2 | 25 | 0 | 1.5 | 0.3 |
| order-playbook | 1 | 15 | 0 | 9.7 | 0.3 |
| zaobao-spec | 1 | 10 | 0 | 1.9 | 0.1 |

## 超线会话
| 会话 | 写缓存(k) | 读缓存(k) | 输出(k) | $ |
|---|---|---|---|---|
| tzzb-distill-daily | 273 | 14705 | 76.8 | 5.85 |
| bili-md-batch:taoge | 399 | 6040 | 65.5 | 4.52 |
| bili-distill-batch:taoge | 201 | 9194 | 58.9 | 4.02 |
| chain-盘中:taoge:review:07 | 322 | 5188 | 49.0 | 3.63 |
| bili-distill-batch:taoge | 243 | 6076 | 55.5 | 3.54 |
| chain-盘中:wudaokongfang:review:07 | 311 | 4856 | 47.2 | 3.47 |
| chain-盘中:control:review:07 | 368 | 3900 | 36.8 | 3.36 |
| tzzb-distill-daily | 224 | 5577 | 54.8 | 3.33 |
| bili-md-batch:taoge | 193 | 5050 | 60.4 | 3.18 |
| bili-md-batch:taoge | 173 | 5021 | 60.9 | 3.09 |
| bili-distill-batch:qushitiange | 143 | 6594 | 49.7 | 3.03 |
