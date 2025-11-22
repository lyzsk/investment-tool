package utils;

import org.springframework.stereotype.Component;

import java.util.Collection;

/**
 * @author sichu huang
 * @since 2025/11/23 00:38
 */
@Component
public class CollUtil {
    public static boolean isEmpty(Collection<?> collection) {
        return collection == null || collection.isEmpty();
    }

    public static boolean isNotEmpty(Collection<?> collection) {
        return !isEmpty(collection);
    }
}
