package enums;

import lombok.AllArgsConstructor;
import lombok.Getter;
import lombok.NoArgsConstructor;

/**
 * EXECUTE_IMMEDIATELY 对应 Quartz 的 MISFIRE_INSTRUCTION_IGNORE_MISFIRES, 忽略所有错失, 尽快连续执行所有积压任务
 * <p/>
 * EXECUTE_ONCE 对应 Quartz 的 MISFIRE_INSTRUCTION_FIRE_ONCE_NOW, 如果错过多次, 只立即执行一次, 然后继续按原计划
 * <p/>
 * ABADON_EXECUTION 对应 Quartz 的 MISFIRE_INSTRUCTION_DO_NOTHING, 错过的触发全部丢弃, 等待下一次正常调度(默认)
 *
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
