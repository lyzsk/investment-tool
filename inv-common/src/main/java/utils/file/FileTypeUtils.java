package utils.file;

import org.springframework.web.multipart.MultipartFile;
import utils.StringUtils;

/**
 * 文件类型工具类
 *
 * @author sichu huang
 * @since 2025/11/30 03:50
 */
public class FileTypeUtils {

    /**
     * 获取extesion
     * <br/>
     * 例如: example.txt -> txt
     *
     * @param file MultipartFile
     * @return java.lang.String 小写后缀名（不含".")
     * @author sichu huang
     * @since 2025/11/30 03:52:42
     */
    public static String getFileExtension(MultipartFile file) {
        String filename = file.getOriginalFilename();
        String extension = StringUtils.EMPTY;
        if (StringUtils.isNotEmpty(filename)) {
            int lastDot = filename.lastIndexOf(StringUtils.DOT);
            if (lastDot > 0 && lastDot < filename.length() - 1) {
                extension = filename.substring(lastDot + 1).toLowerCase();
            }
        }
        return extension;
    }

    /**
     * 获取extesion
     * <br/>
     * 例如: example.txt -> txt
     *
     * @param filename filename
     * @return java.lang.String 小写后缀名（不含".")
     * @author sichu huang
     * @since 2025/11/30 04:00:17
     */
    public static String getFileExtension(String filename) {
        String extension = StringUtils.EMPTY;
        if (StringUtils.isNotEmpty(filename)) {
            int lastDot = filename.lastIndexOf(StringUtils.DOT);
            if (lastDot > 0 && lastDot < filename.length() - 1) {
                extension = filename.substring(lastDot + 1).toLowerCase();
            }
        }
        return extension;
    }
}
