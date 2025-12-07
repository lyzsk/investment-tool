package cn.sichu.system.quartz.service.impl;

import cn.sichu.system.quartz.entity.SysJob;
import cn.sichu.system.quartz.manager.ScheduledTaskManager;
import cn.sichu.system.quartz.mapper.SysJobMapper;
import cn.sichu.system.quartz.service.ISysJobService;
import com.baomidou.mybatisplus.extension.service.impl.ServiceImpl;
import enums.QuartzStatus;
import enums.TableLogic;
import exception.BusinessException;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import utils.StringUtils;

import java.time.LocalDateTime;
import java.util.Objects;

/**
 * @author sichu huang
 * @since 2025/12/07 02:48
 */
@Service
@RequiredArgsConstructor
@Slf4j
public class SysJobServiceImpl extends ServiceImpl<SysJobMapper, SysJob> implements ISysJobService {
    private final ScheduledTaskManager scheduledTaskManager;

    /**
     * 保存定时任务
     *
     * @param job SysJob
     * @author sichu huang
     * @since 2025/12/07 14:54:52
     */
    @Override
    public void saveJob(SysJob job) {
        if (StringUtils.isEmpty(job.getInvokeTarget())) {
            throw new BusinessException("调用目标不能为空");
        }
        if (StringUtils.isEmpty(job.getCronExpression())) {
            throw new BusinessException("定时任务必须设置Cron表达式");
        }
        job.setCreateBy(1L);
        job.setCreateTime(LocalDateTime.now());
        this.save(job);
        if (job.getStatus().equals(QuartzStatus.RUNNING.getCode())) {
            scheduledTaskManager.addJob(job);
        }
    }

    /**
     * 更新定时任务
     *
     * @param job SysJob
     * @author sichu huang
     * @since 2025/12/07 14:55:10
     */
    @Override
    public void updateJob(SysJob job) {
        SysJob existing = this.getById(job.getId());
        if (existing == null || existing.getIsDeleted() == TableLogic.DELETED.getCode()) {
            throw new BusinessException("任务不存在");
        }
        job.setUpdateBy(1L);
        job.setUpdateTime(LocalDateTime.now());
        this.updateById(job);
        boolean statusChanged = !Objects.equals(existing.getStatus(), job.getStatus());
        if (statusChanged) {
            if (job.getStatus().equals(QuartzStatus.RUNNING.getCode())) {
                scheduledTaskManager.addJob(job);
            } else if (job.getStatus().equals(QuartzStatus.PAUSED.getCode())) {
                scheduledTaskManager.removeJob(job.getId());
            }
        } else {
            if (job.getStatus().equals(QuartzStatus.RUNNING.getCode())) {
                scheduledTaskManager.removeJob(job.getId());
                scheduledTaskManager.addJob(job);
            }
        }
    }

    /**
     * 更改任务状态, 启用/暂停
     *
     * @param id     id
     * @param status status
     * @author sichu huang
     * @since 2025/12/07 14:55:25
     */
    @Override
    public void changeStatus(Long id, Integer status) {
        SysJob job = this.getById(id);
        if (job == null || job.getIsDeleted() == TableLogic.DELETED.getCode()) {
            throw new BusinessException("任务不存在");
        }
        job.setStatus(status);
        job.setUpdateBy(1L);
        job.setUpdateTime(LocalDateTime.now());
        this.updateById(job);
        if (status.equals(QuartzStatus.RUNNING.getCode())) {
            scheduledTaskManager.addJob(job);
        } else if (status.equals(QuartzStatus.PAUSED.getCode())) {
            scheduledTaskManager.removeJob(id);
        }
    }

    /**
     * 立即执行一次
     *
     * @param id id
     * @author sichu huang
     * @since 2025/12/07 14:55:46
     */
    @Override
    public void runOnce(Long id) {
        SysJob job = this.getById(id);
        if (job == null || job.getIsDeleted() == TableLogic.DELETED.getCode()) {
            throw new BusinessException("任务不存在");
        }
        scheduledTaskManager.runOnce(id);
        log.info("手动执行任务: {}", job.getJobName());
    }

    /**
     * 删除任务(逻辑删除)
     *
     * @param ids ids
     * @author sichu huang
     * @since 2025/12/07 14:56:06
     */
    @Override
    public void removeJobByIds(Long[] ids) {
        for (Long id : ids) {
            SysJob job = this.getById(id);
            if (job != null && job.getIsDeleted() != TableLogic.DELETED.getCode()) {
                if (job.getStatus().equals(QuartzStatus.RUNNING.getCode())) {
                    scheduledTaskManager.removeJob(id);
                }
                LocalDateTime now = LocalDateTime.now();
                job.setUpdateBy(1L);
                job.setUpdateTime(now);
                job.setIsDeleted(TableLogic.DELETED.getCode());
                job.setDeleteTime(now);
                this.updateById(job);
            }
        }
    }

}
