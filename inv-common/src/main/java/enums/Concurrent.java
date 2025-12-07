package enums;

import lombok.AllArgsConstructor;
import lombok.Getter;
import lombok.NoArgsConstructor;

/**
 * @author sichu huang
 * @since 2025/12/07 02:30
 */
@AllArgsConstructor
@NoArgsConstructor
@Getter
public enum Concurrent {
    ALLOWED(0, "允许"), NOT_ALLOWED(1, "禁止");

    private int code;

    private String msg;

    @Override
    public String toString() {
        return "{" + "\"code\":\"" + code + '\"' + ", \"msg\":\"" + msg + '\"' + '}';
    }
}
