package cn.sichu.system.quartz.enums;

import lombok.AllArgsConstructor;
import lombok.Getter;
import lombok.NoArgsConstructor;

/**
 * @author sichu huang
 * @since 2025/12/07 02:18
 */
@AllArgsConstructor
@NoArgsConstructor
@Getter
public enum QuartzStatus {
    RUNNING(0, "运行"), PAUSED(1, "暂停");

    private int code;

    private String msg;

    @Override
    public String toString() {
        return "{" + "\"code\":\"" + code + '\"' + ", \"msg\":\"" + msg + '\"' + '}';
    }
}
