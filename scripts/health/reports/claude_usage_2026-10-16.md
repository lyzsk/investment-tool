# claude -p 用量 2026-10-16(官方价, 实付按 key 系数折算)

会话 35 个, 合计 $89.2; 超线会话 13 个(写缓存>300k 或 读缓存>5M)

| 类别 | 会话数 | 均写缓存(k) | 均读缓存(k) | 均输出(k) | 合计$ |
|---|---|---|---|---|---|
| bili-md-batch | 10 | 321 | 5186 | 56.7 | 37.8 |
| bili-distill-batch | 7 | 262 | 6883 | 91.1 | 31.6 |
| tzzb-distill-daily | 4 | 124 | 5395 | 36.1 | 9.7 |
| checkmd-tzzb-spec | 4 | 84 | 1535 | 25.0 | 4.9 |
| profile-index | 6 | 72 | 1 | 11.3 | 3.5 |
| checkmd-fage | 1 | 56 | 868 | 13.6 | 0.7 |
| checkmd-cls | 2 | 37 | 379 | 2.5 | 0.6 |
| lhb-seat-style | 1 | 38 | 0 | 8.8 | 0.4 |

## 超线会话
| 会话 | 写缓存(k) | 读缓存(k) | 输出(k) | $ |
|---|---|---|---|---|
| tzzb-distill-daily | 298 | 17666 | 93.9 | 6.90 |
| bili-md-batch:qushitiange | 839 | 4261 | 61.1 | 6.27 |
| bili-distill-batch:qushitiange | 468 | 8318 | 112.4 | 6.25 |
| bili-md-batch:taoge | 414 | 10124 | 91.5 | 5.93 |
| bili-distill-batch:qushitiange | 308 | 9445 | 120.4 | 5.84 |
| bili-distill-batch:qushitiange | 264 | 9538 | 117.2 | 5.57 |
| bili-distill-batch:qushitiange | 244 | 7822 | 106.3 | 4.91 |
| bili-md-batch:taoge | 404 | 7635 | 64.0 | 4.83 |
| bili-md-batch:taoge | 232 | 7227 | 85.1 | 4.31 |
| bili-distill-batch:lubenyuan | 245 | 5657 | 96.0 | 4.28 |
| bili-md-batch:qushitiange | 438 | 3295 | 42.7 | 3.70 |
| bili-md-batch:lubenyuan | 185 | 6320 | 55.4 | 3.30 |
| bili-md-batch:qushitiange | 187 | 5252 | 63.1 | 3.25 |
