package cn.sichu.cls.service;

import java.nio.file.Path;

/**
 * @author sichu huang
 * @since 2026/01/16 16:24
 */
public interface IMarkdownFormatService {

    /**
     * 调用 Node.js 脚本对指定 Markdown 文件进行格式化(模拟 VS Code Ctrl+S)
     *
     * @param markdownFile markdownFile
     * @return boolean
     * @author sichu huang
     * @since 2026/01/16 16:29:38
     */
    boolean formatMarkdownFile(Path markdownFile);
}
