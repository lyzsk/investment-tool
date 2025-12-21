package cn.sichu.system.quartz.service.impl;

import cn.sichu.system.quartz.entity.SysJob;
import cn.sichu.system.quartz.manager.SchedulerManager;
import cn.sichu.system.quartz.mapper.SysJobMapper;
import cn.sichu.system.quartz.service.ISysJobService;
import com.baomidou.mybatisplus.extension.service.impl.ServiceImpl;
import enums.QuartzStatus;
import enums.TableLogic;
import exception.BusinessException;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.quartz.SchedulerException;
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

    private final SchedulerManager schedulerManager;

    /**
     * 保存定时任务
     *
     * @param job SysJob
     * @author sichu huang
     * @since 2025/12/07 14:54:52
     */
    @Override
    public void saveJob(SysJob job) {
        if (StringUtils.isEmpty(job.getCronExpression())) {
            throw new BusinessException("定时任务必须设置Cron表达式");
        }
        job.setCreateTime(LocalDateTime.now());
        this.save(job);
        if (job.getStatus().equals(QuartzStatus.RUNNING.getCode())) {
            try {
                schedulerManager.addJob(job);
            } catch (SchedulerException e) {
                log.error("添加定时任务失败: {}", job.getJobHandlerName(), e);
                throw new BusinessException("任务调度失败: " + e.getMessage());
            }
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
        job.setUpdateTime(LocalDateTime.now());
        this.updateById(job);
        boolean statusChanged = !Objects.equals(existing.getStatus(), job.getStatus());
        try {
            if (statusChanged) {
                if (job.getStatus().equals(QuartzStatus.RUNNING.getCode())) {
                    schedulerManager.addJob(job);
                } else if (job.getStatus().equals(QuartzStatus.PAUSED.getCode())) {
                    schedulerManager.deleteJob(job);
                }
            } else {
                if (job.getStatus().equals(QuartzStatus.RUNNING.getCode())) {
                    schedulerManager.updateJob(job);
                }
            }
        } catch (SchedulerException e) {
            log.error("更新定时任务失败: {}", job.getJobHandlerName(), e);
            throw new BusinessException("任务调度失败: " + e.getMessage());
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
        job.setUpdateTime(LocalDateTime.now());
        this.updateById(job);
        try {
            if (status.equals(QuartzStatus.RUNNING.getCode())) {
                schedulerManager.addJob(job);
            } else if (status.equals(QuartzStatus.PAUSED.getCode())) {
                schedulerManager.deleteJob(job);
            }
        } catch (SchedulerException e) {
            log.error("切换任务状态失败: {}", job.getJobHandlerName(), e);
            throw new BusinessException("任务调度失败: " + e.getMessage());
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
        try {
            schedulerManager.triggerJob(job);
        } catch (SchedulerException e) {
            log.error("手动触发任务失败: {}", job.getJobHandlerName(), e);
            throw new BusinessException("任务触发失败: " + e.getMessage());
        }

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
                try {
                    if (job.getStatus().equals(QuartzStatus.RUNNING.getCode())) {
                        schedulerManager.deleteJob(job);
                    }
                } catch (SchedulerException e) {
                    log.warn("删除调度任务时出错（可能已不存在）: {}", job.getJobHandlerName(), e);
                }
                LocalDateTime now = LocalDateTime.now();
                job.setUpdateTime(now);
                job.setIsDeleted(TableLogic.DELETED.getCode());
                job.setDeleteTime(now);
                this.updateById(job);
            }
        }
    }

}
