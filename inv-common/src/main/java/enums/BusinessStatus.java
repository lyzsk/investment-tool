package enums;

import lombok.AllArgsConstructor;
import lombok.Getter;
import lombok.NoArgsConstructor;

/**
 * @author sichu huang
 * @since 2025/11/30 06:29
 */
@AllArgsConstructor
@NoArgsConstructor
@Getter
public enum BusinessStatus {

    SUCCESS(0, "成功"), FAILED(1, "失败");

    private int code;

    private String msg;

    @Override
    public String toString() {
        return "{" + "\"code\":\"" + code + '\"' + ", \"msg\":\"" + msg + '\"' + '}';
    }
}
