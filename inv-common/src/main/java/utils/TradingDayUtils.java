package utils;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.extern.slf4j.Slf4j;

import java.io.IOException;
import java.io.InputStream;
import java.time.DayOfWeek;
import java.time.LocalDate;
import java.util.Collections;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;

/**
 * 交易日工具类
 * <p/>
 * 节假日数据格式：
 * - 文件路径: classpath:/holiday/{year}.json
 * - 内容格式: { "2026-01-01": true, "2026-01-04": false, ... }
 * - true: 法定节假日（休市）
 * - false: 调休工作日（但 A 股仍休市，仅用于区分是否为普通周末）
 *
 * @author sichu huang
 * @since 2026/01/12 16:48
 */
@Slf4j
public class TradingDayUtils {

    private static final ObjectMapper objectMapper = new ObjectMapper();
    private static final String HOLIDAY_RESOURCE_PREFIX = "holiday/";
    private static final ConcurrentHashMap<String, Map<String, Boolean>> YEAR_HOLIDAY_CACHE =
        new ConcurrentHashMap<>();

    /**
     * 1. 周末直接排除(即使调休上班，A股市也休市)
     * <p/>
     * 2. 周一至周五 查 holiday map
     *
     * @param date LocalDate
     * @return boolean
     * @author sichu huang
     * @since 2026/01/12 16:49:35
     */
    public static boolean isTradingDay(LocalDate date) {
        if (date == null) {
            return false;
        }
        if (date.getDayOfWeek() == DayOfWeek.SATURDAY || date.getDayOfWeek() == DayOfWeek.SUNDAY) {
            return false;
        }
        String year = String.valueOf(date.getYear());
        String dateStr = date.toString();
        Map<String, Boolean> holidayMap = getHolidayMapForYear(year);
        Boolean isOffDay = holidayMap.get(dateStr);
        return isOffDay == null || !isOffDay;
    }

    /**
     * 获取指定年份的节假日映射表
     *
     * @param year yyyy-MM-dd
     * @return java.util.Map<java.lang.String, java.lang.Boolean>
     * @author sichu huang
     * @since 2026/01/12 16:54:21
     */
    private static Map<String, Boolean> getHolidayMapForYear(String year) {
        return YEAR_HOLIDAY_CACHE.computeIfAbsent(year, TradingDayUtils::loadHolidayData);
    }

    /**
     * 从 classpath:/holiday/{year}.json 加载节假日数据
     *
     * @param year yyyy-MM-dd
     * @return java.util.Map<java.lang.String, java.lang.Boolean>
     * @author sichu huang
     * @since 2026/01/12 16:56:50
     */
    private static Map<String, Boolean> loadHolidayData(String year) {
        String resourcePath = HOLIDAY_RESOURCE_PREFIX + year + ".json";
        InputStream inputStream =
            TradingDayUtils.class.getClassLoader().getResourceAsStream(resourcePath);
        try (inputStream) {
            if (inputStream == null) {
                log.warn("节假日数据文件未找到: {}", resourcePath);
                return Collections.emptyMap();
            }
            Map<String, Boolean> result =
                objectMapper.readValue(inputStream, new TypeReference<>() {
                });
            log.info("成功加载节假日数据: {}, 共 {} 条", resourcePath, result.size());
            return result;
        } catch (IOException e) {
            log.error("解析节假日文件失败: {}", resourcePath, e);
            return Collections.emptyMap();
        }
    }
}
