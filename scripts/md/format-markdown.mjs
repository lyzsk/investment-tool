import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";

// 使用前需要:
// cd investment-tool
// npm init -y
// npm install prettier

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

let prettier;
try {
    prettier = await import("prettier");
} catch (e) {
    console.error("❌ 请先运行: npm install prettier");
    process.exit(1);
}

// 1. 从命令行参数获取文件路径
const markdownFilePath = process.argv[2];
if (!markdownFilePath) {
    console.error("❌ 用法: node format-markdown.mjs <file-path>");
    process.exit(1);
}

if (!fs.existsSync(markdownFilePath)) {
    console.error(`❌ 文件不存在: ${markdownFilePath}`);
    process.exit(1);
}

try {
    // 2. 读取文件
    const content = fs.readFileSync(markdownFilePath, "utf8");

    // 3. 通过 filepath 让 Prettier 自动加载 .prettierrc
    const formatted = await prettier.format(content, {
        filepath: markdownFilePath, // ← 这行是关键！
    });

    // 4. 写回文件（覆盖原文件）
    fs.writeFileSync(markdownFilePath, formatted, "utf8");
    console.log(`✅ 已格式化并保存: ${markdownFilePath}`);
    process.exit(0);
} catch (error) {
    console.error("❌ 格式化失败:", error.message);
    console.error(error.stack);
    process.exit(1);
}
