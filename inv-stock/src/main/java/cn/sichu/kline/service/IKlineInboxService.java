package cn.sichu.kline.service;

import org.springframework.web.multipart.MultipartFile;

import java.util.List;

/**
 * K 线 / 分时 / 涨停截图收件箱
 * <p>
 * 原图 downloads/kline/yyyy.MM.dd/(只放原图, 可被 downloadCleanupHandler 物理删除);
 * 案例 / 续画 / 核销状态在 results/kline/(scripts/kline_study/kline_inbox.py 管, 不进 DB)
 *
 * @author sichu huang
 * @since 2026/10/25
 */
public interface IKlineInboxService {

    /**
     * 存原图到 downloads/kline/{date}/(同名同大小跳过, 同名不同大小加序号)
     *
     * @param files 截图
     * @param date  yyyy.MM.dd, 空 = 今天
     * @return java.lang.String "存入 x/跳过 y → 目录"
     * @author sichu huang
     * @since 2026/10/25
     */
    String upload(List<MultipartFile> files, String date);

    /**
     * 跑收件箱: OCR 收件 → 续画未来 3 日 → 导师核销 → 到期对答案(kline_inbox.py --all)
     *
     * @param date  yyyy.MM.dd, 空 = 全部有新图 / 没核销完的日子
     * @param force 盘中也跑 OCR(盘中二次确认用)
     * @return java.lang.String 脚本输出尾部(各图核销状态)
     * @author sichu huang
     * @since 2026/10/25
     */
    String process(String date, boolean force) throws Exception;

    /**
     * downloads/kline/ 超过 retentionDays 的日期目录物理删除(案例和产物在 results/kline/, 不受影响; 下次收件状态记"原图已删")
     *
     * @param retentionDays 保留天数
     * @return java.lang.String
     * @author sichu huang
     * @since 2026/10/25
     */
    String cleanupLocalImages(int retentionDays);
}
