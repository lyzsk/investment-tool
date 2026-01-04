package cn.sichu.system.file.utils;

import exception.UtilException;
import org.springframework.web.multipart.MultipartFile;
import utils.StringUtils;

import java.io.File;
import java.io.FileInputStream;
import java.io.IOException;
import java.io.InputStream;
import java.net.URI;
import java.net.URISyntaxException;
import java.nio.file.Files;
import java.util.Collection;
import java.util.Map;
import java.util.Set;
import java.util.stream.Collectors;

/**
 * 文件处理工具类
 *
 * @author sichu huang
 * @since 2025/11/30 04:06
 */
public class FileUtils {

    private static final Set<String> VALID_IMAGE_EXTENSIONS =
        Set.of("jpg", "jpeg", "png", "gif", "webp", "bmp");

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

    /**
     * 返回mimeType对应的扩展名集合
     *
     * @param mimeTypes mimeTypes
     * @return java.util.Set<java.lang.String>
     * @author sichu huang
     * @since 2025/12/14 09:27:42
     */
    public static Set<String> mimeTypeToExtesions(Collection<String> mimeTypes) {
        Map<String, String> mimeToExt =
            Map.of("image/png", "png", "image/jpeg", "jpg", "image/jpg", "jpg", "image/gif", "gif",
                "image/bmp", "bmp", "application/pdf", "pdf");
        return mimeTypes.stream().map(mimeToExt::get).collect(Collectors.toSet());
    }

    /**
     * 将 java.io.File 转换为 Spring 的 MultipartFile
     *
     * @param file file
     * @return org.springframework.web.multipart.MultipartFile
     * @author sichu huang
     * @since 2025/12/14 07:39:49
     */
    public static MultipartFile toMultipartFile(File file) throws IllegalAccessException {
        if (!file.exists() || !file.isFile()) {
            throw new IllegalAccessException(
                "file not exist or not a file:" + file.getAbsolutePath());
        }
        return new LocalFileMultipartFile(file);
    }

    /**
     * 从图片 URL 推断扩展名
     *
     * @param url 图片 URL
     * @return java.lang.String 小写扩展名, 如"png"
     * @author sichu huang
     * @since 2026/01/03 18:31:00
     */
    public static String guessExtensionFromUrl(String url) {
        if (StringUtils.isEmpty(url)) {
            return null;
        }
        try {
            URI uri = new URI(url);
            String path = uri.getPath();
            if (path == null || path.isEmpty()) {
                return null;
            }
            String filename = new File(path).getName();
            if (filename.isEmpty()) {
                return null;
            }
            String ext = getFileExtension(filename);
            if (ext == null || ext.isEmpty()) {
                return null;
            }
            if (VALID_IMAGE_EXTENSIONS.contains(ext)) {
                return "jpeg".equals(ext) ? "jpg" : ext;
            }
            return null;
        } catch (URISyntaxException e) {
            return null;
        }
    }

    private record LocalFileMultipartFile(File file) implements MultipartFile {

        @Override
        public String getName() {
            return file.getName();
        }

        @Override
        public String getOriginalFilename() {
            return file.getName();
        }

        @Override
        public String getContentType() {
            try {
                String contentType = Files.probeContentType(file.toPath());
                return contentType != null ? contentType : "application/octet-stream";
            } catch (IOException e) {
                return "application/octet-stream";
            }
        }

        @Override
        public boolean isEmpty() {
            return file.length() == 0;
        }

        @Override
        public long getSize() {
            return file.length();
        }

        @Override
        public byte[] getBytes() throws IOException {
            return Files.readAllBytes(file.toPath());
        }

        @Override
        public InputStream getInputStream() throws IOException {
            return new FileInputStream(file);
        }

        @Override
        public void transferTo(File dest) throws IOException, IllegalStateException {
            Files.copy(file.toPath(), dest.toPath());
        }
    }
}
