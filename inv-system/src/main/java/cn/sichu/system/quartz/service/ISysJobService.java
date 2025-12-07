package cn.sichu.system.quartz.service;

import cn.sichu.system.quartz.entity.SysJob;
import com.baomidou.mybatisplus.extension.service.IService;

/**
 * @author sichu huang
 * @since 2025/12/07 02:47
 */
public interface ISysJobService extends IService<SysJob> {

    void saveJob(SysJob job);

    void updateJob(SysJob job);

    void changeStatus(Long id, Integer status);

    void runOnce(Long id);

    void removeJobByIds(Long[] ids);

}
