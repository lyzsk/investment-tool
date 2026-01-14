package cn.sichu.cls;

import cn.sichu.cls.entity.ClsTelegraph;
import cn.sichu.cls.mapper.ClsTelegraphMapper;
import cn.sichu.cls.service.impl.ClsTelegraphServiceImpl;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.transaction.annotation.Transactional;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.time.LocalDate;
import java.time.LocalDateTime;
import java.util.Arrays;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * @author sichu huang
 * @since 2026/01/14 16:21
 */
@SpringBootTest
@ActiveProfiles("test")
@Transactional
public class ClsTelegraphServiceImplTest {
    private static final LocalDate TEST_DATE = LocalDate.of(2026, 1, 14);
    @Autowired
    private ClsTelegraphServiceImpl clsTelegraphService;
    @Autowired
    private ClsTelegraphMapper clsTelegraphMapper;

    @BeforeEach
    void setUp() {
        clsTelegraphMapper.delete(null);

        // 确保测试目录存在
        try {
            Path markdownDir =
                Paths.get(System.getProperty("user.home"), "dev/investment-tool/stock");
            Files.createDirectories(markdownDir);

            // 创建空的 Markdown 文件
            Path markdownFile = markdownDir.resolve(
                TEST_DATE.format(java.time.format.DateTimeFormatter.ofPattern("yyyy-MM-dd"))
                    + ".md");
            String templateContent = """
                # 2026-01-14 星期三

                ## 加红电报


                ## 其他内容
                """;
            Files.write(markdownFile, templateContent.getBytes(StandardCharsets.UTF_8));
        } catch (IOException e) {
            throw new RuntimeException("Failed to prepare test markdown file", e);
        }
    }

    @Test
    void testAppendRedTelegraphs_ImagesShouldBeIncludedInMarkdown() {
        // 准备测试数据 - 包含 images 字段
        List<String> expectedImages =
            Arrays.asList("https://example.com/image1.jpg", "https://example.com/image2.jpg");

        ClsTelegraph telegraph = new ClsTelegraph();
        telegraph.setClsId(12345L);
        telegraph.setTitle("测试标题");
        telegraph.setBrief("测试摘要");
        telegraph.setContent("测试内容");
        telegraph.setLevel("B"); // 注意：数据库中 level 应该是 "B" 而不是 "RED"
        telegraph.setPublishTime(TEST_DATE.atStartOfDay().plusHours(10)); // 在测试日期当天
        telegraph.setAuthor("测试作者");
        telegraph.setImages(expectedImages);
        telegraph.setStatus(1);
        telegraph.setCreateTime(LocalDateTime.now());
        telegraph.setUpdateTime(LocalDateTime.now());
        telegraph.setIsDeleted(0); // 确保未删除

        // 1. 先保存到数据库
        boolean saved = clsTelegraphService.save(telegraph);
        assertThat(saved).isTrue();

        // 2. 调用 appendRedTelegraphs 方法（传 LocalDate）
        boolean result = clsTelegraphService.appendRedTelegraphs(TEST_DATE);
        assertThat(result).isTrue();

        // 3. 验证 Markdown 文件是否包含图片链接
        try {
            Path markdownFile =
                Paths.get(System.getProperty("user.home"), "dev/investment-tool/stock",
                    TEST_DATE + ".md");
            String content = Files.readString(markdownFile, StandardCharsets.UTF_8);

            // 验证电报链接存在
            assertThat(content).contains("[测试摘要]");
            assertThat(content).contains("https://www.cls.cn/detail/12345");

            // 验证图片链接存在
            assertThat(content).contains("![](" + expectedImages.get(0) + ")");
            assertThat(content).contains("![](" + expectedImages.get(1) + ")");

        } catch (IOException e) {
            throw new RuntimeException("Failed to read markdown file", e);
        }
    }

    @Test
    void testDatabaseRead_RetrieveTelegraphWithImages() {
        // 单独测试数据库读写 Images 字段
        List<String> expectedImages = Arrays.asList("https://test.com/img.jpg");

        ClsTelegraph telegraph = new ClsTelegraph();
        telegraph.setClsId(67890L);
        telegraph.setTitle("DB Test");
        telegraph.setLevel("B");
        telegraph.setPublishTime(TEST_DATE.atStartOfDay().plusHours(9));
        telegraph.setImages(expectedImages);
        telegraph.setStatus(1);
        telegraph.setCreateTime(LocalDateTime.now());
        telegraph.setUpdateTime(LocalDateTime.now());
        telegraph.setIsDeleted(0);

        // 保存
        clsTelegraphService.save(telegraph);

        // 查询
        List<ClsTelegraph> retrievedList = clsTelegraphMapper.selectList(
            new LambdaQueryWrapper<ClsTelegraph>().eq(ClsTelegraph::getClsId, 67890L));

        assertThat(retrievedList).hasSize(1);
        ClsTelegraph retrieved = retrievedList.get(0);

        assertThat(retrieved.getImages()).isNotNull();
        assertThat(retrieved.getImages()).isEqualTo(expectedImages);
    }
}