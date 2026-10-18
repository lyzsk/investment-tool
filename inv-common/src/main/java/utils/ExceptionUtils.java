package utils;

import java.io.PrintWriter;
import java.io.StringWriter;

/**
 * @author sichu huang
 * @since 2025/12/07 16:46
 */
public class ExceptionUtils {

    /**
     * 将异常堆栈信息转换为字符串(截断)
     *
     * @param throwable 异常对象，若为 {@code null} 则返回空字符串
     * @param maxLength 允许的最大字符串长度(varchar)
     * @return java.lang.String
     * @author sichu huang
     * @since 2025/12/21 01:19:10
     */
    public static String getStacktrace(Throwable throwable, int maxLength) {
        if (throwable == null) {
            return StringUtils.EMPTY;
        }
        StringWriter sw = new StringWriter();
        PrintWriter pw = new PrintWriter(sw);
        throwable.printStackTrace(pw);
        String stackTrace = sw.toString();
        if (maxLength > 0 && stackTrace.length() > maxLength) {
            return stackTrace.substring(0, maxLength);
        }
        return stackTrace;
    }

    /**
     * 将异常转换为完整的堆栈跟踪字符串
     *
     * @param throwable 异常对象
     * @return java.lang.String 堆栈字符串，若为 null 则返回 "null"
     * @author sichu huang
     * @since 2025/12/21 01:16:44
     */
    public static String getStacktrace(Throwable throwable) {
        if (throwable == null) {
            return "null";
        }
        StringWriter sw = new StringWriter();
        PrintWriter pw = new PrintWriter(sw);
        throwable.printStackTrace(pw);
        pw.flush();
        return sw.toString();
    }
}
