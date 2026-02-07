package cn.sichu.system.handler;

import com.baomidou.mybatisplus.core.handlers.MetaObjectHandler;
import enums.TableLogic;
import org.apache.ibatis.reflection.MetaObject;
import org.springframework.stereotype.Component;

import java.time.LocalDateTime;
import java.util.Objects;

/**
 * @author sichu huang
 * @since 2026/01/24 13:11
 */
@Component
public class MyMetaObjectHandler implements MetaObjectHandler {

    @Override
    public void insertFill(MetaObject metaObject) {
        this.strictInsertFill(metaObject, "createBy", this::getUserId, Long.class);
        this.strictInsertFill(metaObject, "createTime", LocalDateTime::now, LocalDateTime.class);
    }

    @Override
    public void updateFill(MetaObject metaObject) {
        this.strictUpdateFill(metaObject, "updateBy", this::getUserId, Long.class);
        this.strictUpdateFill(metaObject, "updateTime", LocalDateTime::now, LocalDateTime.class);
        Object isDeleted = metaObject.getValue("isDeleted");
        if (Objects.equals(isDeleted, TableLogic.DELETED.getCode())) {
            metaObject.setValue("deleteBy", getUserId());
            metaObject.setValue("deleteTime", LocalDateTime.now());
        }
    }

    private Long getUserId() {
        return 1L;
    }
}
