package enums;

import lombok.AllArgsConstructor;
import lombok.Getter;
import lombok.NoArgsConstructor;

/**
 * @author sichu huang
 * @since 2025/11/30 06:33
 */
@AllArgsConstructor
@NoArgsConstructor
@Getter
public enum TableLogic {

    NOT_DELETED(0, "未删除"), DELETED(1, "已删除");

    private int code;

    private String msg;

    @Override
    public String toString() {
        return "{" + "\"code\":\"" + code + '\"' + ", \"msg\":\"" + msg + '\"' + '}';
    }
}
