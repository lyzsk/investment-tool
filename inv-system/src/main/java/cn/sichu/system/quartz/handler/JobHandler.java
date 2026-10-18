package cn.sichu.system.quartz.handler;

/**
 * @author sichu huang
 * @since 2025/12/21 01:04
 */
public interface JobHandler {
    /**
     * @param params params
     * @return java.lang.String
     * @author sichu huang
     * @since 2025/12/21 01:05:08
     */
    String execute(String params) throws Exception;
}
