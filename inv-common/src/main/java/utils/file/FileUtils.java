package utils.file;

import exception.UtilException;

import java.io.File;

/**
 * 文件处理工具类
 *
 * @author sichu huang
 * @since 2025/11/30 04:06
 */
public class FileUtils {

    public FileUtils() {
        throw new UtilException("FileUtils error");
    }

    /**
     * 删除文件
     *
     * @param absolutePath 绝对路径
     * @return boolean
     * @author sichu huang
     * @since 2025/11/30 04:08:29
     */
    public static boolean deleteFile(String absolutePath) {
        boolean flag = false;
        File file = new File(absolutePath);
        if (file.isFile() && file.exists()) {
            flag = file.delete();
        }
        return flag;
    }
}
