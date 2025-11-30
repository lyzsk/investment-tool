package utils;

import exception.UtilException;

import java.util.concurrent.atomic.AtomicLong;

/**
 * 单机本地部署snowflake生成id
 *
 * @author sichu huang
 * @since 2025/11/30 04:11
 */
public class IdUtils {
    /* 起始时间戳 2025-01-01 00:00:00 UTC */
    private static final long EPOCH = 1735689600000L;

    /* 序列号(每毫秒内自增) */
    private static final AtomicLong sequence = new AtomicLong(0);

    /* 上一次生成 ID 的时间戳 */
    private static volatile long lastTimestamp = -1L;

    public IdUtils() {
        throw new UtilException("IdUtils error");
    }

    /**
     * 1.时钟回拨,抛异常
     * <br/>
     * 2.同一毫秒内，序列号自增, 若序列号溢出，等待下一毫秒
     * <br/>
     * 3.不同毫秒内，序列号置为 0
     *
     * @return long 获取下一个雪花 ID
     * @author sichu huang
     * @since 2025/11/30 04:17:47
     */
    public static synchronized long nextId() {
        long timestamp = System.currentTimeMillis();
        if (timestamp < lastTimestamp) {
            throw new RuntimeException("Clock moved backwards. Refusing to generate id.");
        }
        if (lastTimestamp == timestamp) {
            long seq = sequence.incrementAndGet() & 0xFFF;
            if (seq == 0) {
                timestamp = waitNextMillis(lastTimestamp);
            }
        } else {
            sequence.set(0);
        }
        lastTimestamp = timestamp;
        return ((timestamp - EPOCH) << 22) | (sequence.get() & 0xFFF);
    }

    public static String getSnowflakeNextId() {
        return String.valueOf(nextId());
    }

    private static long waitNextMillis(long lastTimestamp) {
        long timestamp = System.currentTimeMillis();
        while (timestamp <= lastTimestamp) {
            timestamp = System.currentTimeMillis();
        }
        return timestamp;
    }
}
