package enums;

import lombok.AllArgsConstructor;
import lombok.Getter;
import lombok.NoArgsConstructor;

/**
 * @author sichu huang
 * @since 2026/01/05 16:29
 */
@AllArgsConstructor
@NoArgsConstructor
@Getter
public enum QuartzStatus {

    RUNNING(0, "运行"), PAUSE(1, "暂停");

    private int code;

    private String msg;

    @Override
    public String toString() {
        return "{" + "\"code\":\"" + code + '\"' + ", \"msg\":\"" + msg + '\"' + '}';
    }

}
