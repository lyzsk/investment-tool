package utils;

import exception.BusinessException;

import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.concurrent.TimeUnit;

/**
 * 子进程运行器
 *
 * @author sichu huang
 * @since 2026/10/11
 **/
public class ProcessUtils {
    private ProcessUtils() {
    }

    public static Result run(ProcessBuilder pb, long timeoutMin) throws Exception {
        pb.redirectErrorStream(true);
        Process proc = pb.start();
        StringBuilder tail = new StringBuilder();
        Thread reader = new Thread(() -> {
            try (BufferedReader br = new BufferedReader(
                new InputStreamReader(proc.getInputStream(), StandardCharsets.UTF_8))) {
                String line;
                while ((line = br.readLine()) != null) {
                    synchronized (tail) {
                        tail.append(line).append('\n');
                        if (tail.length() > 4000) {
                            tail.delete(0, tail.length() - 4000);
                        }
                    }
                }
            } catch (Exception ignored) {
                /* 进程被杀时流关闭, 正常结束 */
            }
        }, "proc-out-" + proc.pid());
        reader.setDaemon(true);
        reader.start();
        if (!proc.waitFor(timeoutMin, TimeUnit.MINUTES)) {
            /* 先杀子孙(claude.exe/node), 防孤儿 */
            proc.descendants()
                .forEach(ProcessHandle::destroyForcibly);
            proc.destroyForcibly();
            reader.join(3000);
            synchronized (tail) {
                return new Result(-1, tail.toString(), true);
            }
        }
        reader.join(5000);
        synchronized (tail) {
            return new Result(proc.exitValue(), tail.toString(), false);
        }
    }

    /**
     * 运行子进程, 超时或退出码非 0 直接抛 BusinessException(带输出尾部), 成功返回输出尾部
     *
     * @author sichu huang
     * @param pb pb
     * @param timeoutMin timeoutMin
     * @param label 日志/异常里的脚本名
     * @since 2026/10/11
     * @return java.lang.String
     **/
    public static String runChecked(ProcessBuilder pb, long timeoutMin, String label) throws Exception {
        Result res = run(pb, timeoutMin);
        if (res.timedOut()) {
            throw new BusinessException(label + " 超时 " + timeoutMin + "min(进程树已杀), 输出尾部: " + res.tail());
        }
        if (res.exit() != 0) {
            throw new BusinessException(label + " 失败 exit=" + res.exit() + ", 输出尾部: " + res.tail());
        }
        return res.tail();
    }

    /**
     * 项目 python 解释器: 先 scripts/venv, 不存在再用 PATH 里的 python
     *
     * @author sichu huang
     * @param rootDir 项目根目录
     * @since 2026/10/11
     * @return java.lang.String
     **/
    public static String venvPython(String rootDir) {
        Path venv = Paths.get(rootDir, "scripts", "venv", "Scripts", "python.exe");
        return Files.exists(venv) ? venv.toString() : "python";
    }

    /**
     * 运行结果: exit=退出码(超时为 -1), tail=输出尾部
     *
     * @author sichu huang
     * @since 2026/10/11
     **/
    public record Result(int exit, String tail, boolean timedOut) {
    }
}
