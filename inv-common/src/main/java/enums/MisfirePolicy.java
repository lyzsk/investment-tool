package enums;

import lombok.AllArgsConstructor;
import lombok.Getter;
import lombok.NoArgsConstructor;

/**
 * @author sichu huang
 * @since 2025/12/07 02:26
 */
@AllArgsConstructor
@NoArgsConstructor
@Getter
public enum MisfirePolicy {

    EXECUTE_IMMEDIATELY(0, "立即执行"), EXECUTE_ONCE(1, "执行一次"), ABADON_EXECUTION(2,
        "放弃执行");

    private int code;

    private String msg;

    @Override
    public String toString() {
        return "{" + "\"code\":\"" + code + '\"' + ", \"msg\":\"" + msg + '\"' + '}';
    }
}
