package enums;

import lombok.AllArgsConstructor;
import lombok.Getter;
import lombok.NoArgsConstructor;

/**
 * @author sichu huang
 * @since 2025/11/30 06:20
 */
@AllArgsConstructor
@NoArgsConstructor
@Getter
public enum ProcessStatus {
    UNPROCESSED(0, "未处理"), PROCESSED(1, "已处理"), PROCESS_FAILED(2, "处理失败");

    private int code;

    private String msg;

    @Override
    public String toString() {
        return "{" + "\"code\":\"" + code + '\"' + ", \"msg\":\"" + msg + '\"' + '}';
    }

}
