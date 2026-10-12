package utils;

import org.springframework.stereotype.Component;

import java.util.ArrayList;
import java.util.Collection;
import java.util.List;

/**
 * @author sichu huang
 * @since 2025/11/23 00:38
 */
@Component
public class CollectionUtils {
    public static boolean isEmpty(Collection<?> collection) {
        return collection == null || collection.isEmpty();
    }

    public static boolean isNotEmpty(Collection<?> collection) {
        return !isEmpty(collection);
    }

    /**
     * 按固定大小切分 list(批量插入分批用); 返回原 list 的子视图, 不复制元素
     *
     * @author sichu huang
     * @param list 原列表
     * @param size 每批大小(>0)
     * @since 2026/10/11
     * @return java.util.List<java.util.List<T>>
     **/
    public static <T> List<List<T>> partition(List<T> list, int size) {
        if (size <= 0) {
            throw new IllegalArgumentException("size 必须 > 0: " + size);
        }
        List<List<T>> batches = new ArrayList<>();
        if (isEmpty(list)) {
            return batches;
        }
        for (int i = 0; i < list.size(); i += size) {
            batches.add(list.subList(i, Math.min(i + size, list.size())));
        }
        return batches;
    }
}
